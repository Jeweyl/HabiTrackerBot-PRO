<template>
  <div class="page center">
    <div class="card" style="max-width: 480px; width: 100%">
      <h1 class="error-title" style="margin-top: 0">{{ title }}</h1>
      <p class="muted">{{ message }}</p>
      <p class="muted" style="font-size: 0.9rem">
        Open the bot → Statistics → «Open dashboard» for a new link.
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useRoute } from "vue-router"

const route = useRoute()

const reason = computed(() => {
  const raw = route.query.reason
  const value = Array.isArray(raw) ? raw[0] : raw
  return String(value || "unknown")
})

const title = computed(() => {
  switch (reason.value) {
    case "missing_token":
      return "Link incomplete"
    case "invalid_token":
      return "Link invalid or expired"
    case "not_authenticated":
      return "Session required"
    case "exchange_failed":
      return "Could not sign in"
    default:
      return "Something went wrong"
  }
})

const message = computed(() => {
  switch (reason.value) {
    case "missing_token":
      return "This page needs a one-time token from the Telegram bot."
    case "invalid_token":
      return "The one-time link was already used, expired, or is invalid."
    case "not_authenticated":
      return "Open a fresh dashboard link from the bot to continue."
    case "exchange_failed":
      return "The server could not exchange your token. Try again later."
    default:
      return "Please request a new dashboard link from the bot."
  }
})
</script>
