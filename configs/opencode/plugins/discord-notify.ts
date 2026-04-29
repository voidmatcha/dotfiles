// Minimal Discord webhook notifier for opencode.
//
// Fires a single Discord message when a session becomes idle with:
//   - title:       ✅ [{project}] {session_title}
//   - description: last assistant message (truncated, summarises what was done)
//   - url:         opencode web base URL (only when reachable from outside loopback,
//                  e.g. the LaunchAgent's instance bound to a Tailscale IP — keeps
//                  notifications private to the tailnet, never creates a public share)
//   - color:       green
//
// Configuration (read from environment, typically sourced by the LaunchAgent
// wrapper from ~/.opencode-secrets.env):
//
//   DISCORD_WEBHOOK_URL   required — channel webhook URL
// If DISCORD_WEBHOOK_URL is unset, the plugin loads but does nothing.

import type { Plugin } from "@opencode-ai/plugin"

const COLOR_GREEN = 0x57f287
const TITLE_MAX_LENGTH = 240 // Discord embed title limit is 256
const DESCRIPTION_MAX_LENGTH = 600 // keep notifications scannable on iPhone lock screen

type DiscordEmbed = {
  title: string
  color: number
  url?: string
  description?: string
}

type DiscordWebhookBody = {
  content: string
  embeds: DiscordEmbed[]
  allowed_mentions?: {
    users: string[]
  }
}

type RuntimeInput = {
  client: {
    session: {
      get(input: { path: { id: string } }): Promise<
        | {
            data?: {
              title?: string
              directory?: string
            }
          }
        | undefined
      >
    }
  }
  serverUrl?: unknown
}

type MessageUpdatedProperties = {
  info?: {
    id?: string
    role?: string
  }
}

type MessagePartUpdatedProperties = {
  part?: {
    sessionID?: string
    messageID?: string
    type?: string
    text?: unknown
  }
}

type SessionIdleProperties = {
  sessionID?: string
}

type SessionStatusProperties = {
  sessionID?: string
  status?: {
    type?: string
  }
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value
  return value.slice(0, max - 1) + "…"
}

function projectName(directory: string | undefined): string | undefined {
  if (!directory) return undefined
  const parts = directory.split("/").filter(Boolean)
  return parts.pop()
}

function externallyReachable(serverUrl: unknown): string | undefined {
  if (!serverUrl) return undefined
  const url = String(serverUrl)
  try {
    const u = new URL(url)
    if (u.hostname === "127.0.0.1" || u.hostname === "localhost" || u.hostname === "::1") {
      return undefined
    }
    return url
  } catch {
    return undefined
  }
}

function buildSessionUrl(
  serverUrl: string,
  directory: string | undefined,
  sessionID: string,
): string {
  const baseUrl = serverUrl.replace(/\/$/, "")
  if (!directory) return baseUrl
  const projectSlug = Buffer.from(directory, "utf-8")
    .toString("base64")
    .replace(/=+$/, "")
  return `${baseUrl}/${projectSlug}/session/${sessionID}`
}

function createDiscordWebhookBody(input: {
  title: string
  summary?: string
  url?: string
  userID?: string
}): DiscordWebhookBody {
  const title = truncate(input.title, TITLE_MAX_LENGTH)
  const embed: DiscordEmbed = {
    title,
    color: COLOR_GREEN,
  }
  if (input.url) embed.url = input.url
  if (input.summary) embed.description = truncate(input.summary, DESCRIPTION_MAX_LENGTH)

  if (input.userID) {
    return {
      content: `<@${input.userID}> ${title}`,
      embeds: [embed],
      allowed_mentions: { users: [input.userID] },
    }
  }

  return { content: title, embeds: [embed] }
}

function idleSessionID(eventType: string, properties: unknown): string | undefined {
  if (eventType === "session.idle") {
    return (properties as SessionIdleProperties | undefined)?.sessionID
  }

  if (eventType === "session.status") {
    const status = properties as SessionStatusProperties | undefined
    return status?.status?.type === "idle" ? status.sessionID : undefined
  }

  return undefined
}

const plugin: Plugin = async (input) => {
  const webhookUrl = process.env.DISCORD_WEBHOOK_URL?.trim()
  const userID = process.env.DISCORD_USER_ID?.trim()
  const runtimeInput = input as unknown as RuntimeInput
  const client = runtimeInput.client
  const reachableServerUrl = externallyReachable(runtimeInput.serverUrl)

  if (!webhookUrl) {
    // Plugin disabled — no webhook configured.
    return { event: async () => {} }
  }

  const messageRoleById = new Map<string, "user" | "assistant">()
  const lastAssistantTextBySession = new Map<string, string>()

  return {
    event: async ({ event }) => {
      const eventType = event.type as string

      if (eventType === "message.updated") {
        const info = (event.properties as MessageUpdatedProperties | undefined)?.info
        const id = info?.id
        const role = info?.role
        if (id && (role === "user" || role === "assistant")) {
          messageRoleById.set(id, role)
        }
        return
      }

      if (eventType === "message.part.updated") {
        const part = (event.properties as MessagePartUpdatedProperties | undefined)?.part
        const sessionID = part?.sessionID
        const messageID = part?.messageID
        if (!sessionID || !messageID || part?.type !== "text") return
        if (messageRoleById.get(messageID) !== "assistant") return
        const text = typeof part.text === "string" ? part.text : ""
        if (text.trim()) lastAssistantTextBySession.set(sessionID, text)
        return
      }

      const sessionID = idleSessionID(eventType, event.properties)
      if (!sessionID) return

      try {
        const sessionResp = (await client.session.get({
          path: { id: sessionID },
        })) as { data?: { title?: string; directory?: string } } | undefined
        const session = sessionResp?.data
        const title = session?.title?.trim() || "untitled"
        const project = projectName(session?.directory)

        const headline = project ? `✅ [${project}] ${title}` : `✅ ${title}`
        const summary = lastAssistantTextBySession.get(sessionID)?.trim()
        lastAssistantTextBySession.delete(sessionID)

        const url = reachableServerUrl
          ? buildSessionUrl(reachableServerUrl, session?.directory, sessionID)
          : undefined
        const body = createDiscordWebhookBody({
          title: headline,
          summary,
          url,
          userID,
        })

        const res = await fetch(webhookUrl, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        })
        if (!res.ok) {
          console.error(
            `[discord-notify] webhook failed: ${res.status} ${res.statusText}`,
          )
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        console.error("[discord-notify] error:", message)
      }
    },
  }
}

export default plugin
