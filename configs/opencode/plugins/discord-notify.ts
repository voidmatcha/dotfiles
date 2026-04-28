// Minimal Discord webhook notifier for opencode.
//
// Fires a single embed per `session.idle` event with:
//   - title:       ✅ [{project}] {session_title}
//   - description: last assistant message (truncated, summarises what was done)
//   - url:         opencode web base URL (only when reachable from outside loopback,
//                  e.g. the LaunchAgent's instance bound to a Tailscale IP — keeps
//                  notifications private to the tailnet, never creates a public share)
//   - color:       green
//   - mention:     optional <@user_id> for guaranteed iPhone push
//
// Configuration (read from environment, typically sourced by the LaunchAgent
// wrapper from ~/.opencode-secrets.env):
//
//   DISCORD_WEBHOOK_URL   required — channel webhook URL
//   DISCORD_USER_ID       optional — numeric Discord user ID for mention
//
// If DISCORD_WEBHOOK_URL is unset, the plugin loads but does nothing.

import type { Plugin } from "@opencode-ai/plugin"

const COLOR_GREEN = 0x57f287
const TITLE_MAX_LENGTH = 240 // Discord embed title limit is 256
const DESCRIPTION_MAX_LENGTH = 600 // keep notifications scannable on iPhone lock screen

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

const plugin: Plugin = async (input) => {
  const webhookUrl = process.env.DISCORD_WEBHOOK_URL?.trim()
  const userID = process.env.DISCORD_USER_ID?.trim()
  const client = (input as any).client
  const reachableServerUrl = externallyReachable((input as any).serverUrl)

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
        const info = (event.properties as any)?.info
        const id = info?.id as string | undefined
        const role = info?.role as string | undefined
        if (id && (role === "user" || role === "assistant")) {
          messageRoleById.set(id, role)
        }
        return
      }

      if (eventType === "message.part.updated") {
        const part = (event.properties as any)?.part
        const sessionID = part?.sessionID as string | undefined
        const messageID = part?.messageID as string | undefined
        if (!sessionID || !messageID || part?.type !== "text") return
        if (messageRoleById.get(messageID) !== "assistant") return
        const text = typeof part.text === "string" ? part.text : ""
        if (text.trim()) lastAssistantTextBySession.set(sessionID, text)
        return
      }

      if (eventType !== "session.idle") return
      const sessionID = (event.properties as { sessionID?: string })?.sessionID
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

        const embed: Record<string, unknown> = {
          title: truncate(headline, TITLE_MAX_LENGTH),
          color: COLOR_GREEN,
        }
        if (reachableServerUrl) {
          embed.url = buildSessionUrl(reachableServerUrl, session?.directory, sessionID)
        }
        if (summary) embed.description = truncate(summary, DESCRIPTION_MAX_LENGTH)

        const body: Record<string, unknown> = { embeds: [embed] }
        if (userID) {
          body.content = `<@${userID}>`
          body.allowed_mentions = { users: [userID] }
        }

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
