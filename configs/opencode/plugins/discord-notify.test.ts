import assert from "node:assert/strict"
import { describe, test } from "node:test"

import { createDiscordWebhookBody } from "./discord-notify.ts"

describe("createDiscordWebhookBody", () => {
  test("does not mention the user so iOS notification previews show embed content", () => {
    const body = createDiscordWebhookBody({
      title: "✅ [dotfiles] Update notifier",
      summary: "Removed Discord mentions from opencode idle notifications.",
      url: "http://100.64.0.1:4096/project/session/ses_example",
    })

    assert.equal(Object.hasOwn(body, "content"), false)
    assert.equal(Object.hasOwn(body, "allowed_mentions"), false)
    assert.deepEqual(body.embeds[0], {
      title: "✅ [dotfiles] Update notifier",
      description: "Removed Discord mentions from opencode idle notifications.",
      url: "http://100.64.0.1:4096/project/session/ses_example",
      color: 0x57f287,
    })
  })
})
