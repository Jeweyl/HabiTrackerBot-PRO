<template>
  <div class="page center">
    <div class="card" style="max-width: 420px; width: 100%">
      <div class="spinner" aria-hidden="true" />
      <h1 style="margin: 0 0 0.5rem; font-size: 1.25rem">Signing in…</h1>
      <p class="muted" style="margin: 0">
        Exchanging your one-time link for a secure session.
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import { exchangeToken } from "@/api/auth"
import { ApiError } from "@/api/client"
import { setAccessToken } from "@/auth/session"

const route = useRoute()
const router = useRouter()
const controller = new AbortController()

onMounted(async () => {
  const raw = route.query.token
  const token = Array.isArray(raw) ? raw[0] : raw

  if (!token || !String(token).trim()) {
    await router.replace({
      name: "error",
      query: { reason: "missing_token" },
    })
    return
  }

  try {
    const result = await exchangeToken(String(token).trim(), controller.signal)
    if (!result?.access_token) {
      await router.replace({
        name: "error",
        query: { reason: "invalid_token" },
      })
      return
    }
    setAccessToken(result.access_token)
    await router.replace({ name: "dashboard" })
  } catch (err) {
    if (controller.signal.aborted) {
      return
    }
    const reason =
      err instanceof ApiError && err.status === 401
        ? "invalid_token"
        : "exchange_failed"
    await router.replace({ name: "error", query: { reason } })
  }
})

onUnmounted(() => {
  controller.abort()
})
</script>
