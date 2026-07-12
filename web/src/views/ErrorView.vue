<template>
  <div class="page center">
    <div class="card" style="max-width: 480px; width: 100%">
      <h1 class="error-title" style="margin-top: 0">{{ title }}</h1>
      <p class="muted">{{ message }}</p>
      <p class="muted" style="font-size: 0.9rem">
        {{ t("error.hint", lang) }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useRoute } from "vue-router"
import { resolveLang, t, type Lang } from "@/i18n"

const route = useRoute()
const lang = ref<Lang>(resolveLang())

const reason = computed(() => {
  const raw = route.query.reason
  const value = Array.isArray(raw) ? raw[0] : raw
  return String(value || "unknown")
})

const title = computed(() => {
  switch (reason.value) {
    case "missing_token":
      return t("error.missing_token.title", lang.value)
    case "invalid_token":
      return t("error.invalid_token.title", lang.value)
    case "not_authenticated":
      return t("error.not_authenticated.title", lang.value)
    case "exchange_failed":
      return t("error.exchange_failed.title", lang.value)
    default:
      return t("error.unknown.title", lang.value)
  }
})

const message = computed(() => {
  switch (reason.value) {
    case "missing_token":
      return t("error.missing_token.body", lang.value)
    case "invalid_token":
      return t("error.invalid_token.body", lang.value)
    case "not_authenticated":
      return t("error.not_authenticated.body", lang.value)
    case "exchange_failed":
      return t("error.exchange_failed.body", lang.value)
    default:
      return t("error.unknown.body", lang.value)
  }
})
</script>
