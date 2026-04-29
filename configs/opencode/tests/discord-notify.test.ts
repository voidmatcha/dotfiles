import assert from "node:assert/strict"
import { afterEach, describe, test } from "node:test"

import plugin from "../plugins/discord-notify.ts"

type DiscordWebhookBody = {
  content: string
  embeds: Array<{
    title: string
    url?: string
    color: number
    description?: string
  }>
  allowed_mentions?: {
    users: string[]
  }
}

type NotifierPlugin = (input: unknown) => Promise<{
  event(args: { event: { type: string; properties?: unknown } }): Promise<void>
}>

const originalFetch = globalThis.fetch
const originalWebhook = process.env.DISCORD_WEBHOOK_URL
const originalUserID = process.env.DISCORD_USER_ID

afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalWebhook === undefined) delete process.env.DISCORD_WEBHOOK_URL
  else process.env.DISCORD_WEBHOOK_URL = originalWebhook
  if (originalUserID === undefined) delete process.env.DISCORD_USER_ID
  else process.env.DISCORD_USER_ID = originalUserID
})

async function runIdleEvent(event: { type: string; properties?: unknown }) {
  let body: DiscordWebhookBody | undefined
  globalThis.fetch = async (_url, init) => {
    body = JSON.parse(String(init?.body)) as DiscordWebhookBody
    return new Response(null, { status: 204 })
  }

  process.env.DISCORD_WEBHOOK_URL = "https://discord.example/webhook"
  process.env.DISCORD_USER_ID = "123456789012345678"

  const notifier = plugin as unknown as NotifierPlugin
  const hooks = await notifier({
    serverUrl: "http://100.64.0.1:4096",
    client: {
      session: {
        get: async () => ({
          data: {
            title: "Update notifier",
            directory: "/Users/yongjae/Downloads/dotfiles",
          },
        }),
      },
    },
  })

  await hooks.event({
    event: {
      type: "message.updated",
      properties: { info: { id: "msg_1", role: "assistant" } },
    },
  })
  await hooks.event({
    event: {
      type: "message.part.updated",
      properties: {
        part: {
          sessionID: "ses_example",
          messageID: "msg_1",
          type: "text",
          text: "Readable notification summary.",
        },
      },
    },
  })
  await hooks.event({ event })

  assert.ok(body)
  return body
}

describe("discord notifier", () => {
  test("sends readable mention payload on canonical session.status idle", async () => {
    const body = await runIdleEvent({
      type: "session.status",
      properties: { sessionID: "ses_example", status: { type: "idle" } },
    })

    assert.equal(
      body.content,
      "<@123456789012345678> ✅ [dotfiles] Update notifier",
    )
    assert.deepEqual(body.allowed_mentions, { users: ["123456789012345678"] })
    assert.equal(body.embeds[0].description, "Readable notification summary.")
    assert.equal(
      body.embeds[0].url,
      "http://100.64.0.1:4096/L1VzZXJzL3lvbmdqYWUvRG93bmxvYWRzL2RvdGZpbGVz/session/ses_example",
    )
  })

  test("keeps deprecated session.idle as a fallback", async () => {
    const body = await runIdleEvent({
      type: "session.idle",
      properties: { sessionID: "ses_example" },
    })

    assert.equal(
      body.content,
      "<@123456789012345678> ✅ [dotfiles] Update notifier",
    )
  })
})
