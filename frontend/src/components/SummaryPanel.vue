<script setup lang="ts">
import { ref, computed } from "vue";
import { marked } from "marked";
import { fetchSummary } from "../api/client";

const props = defineProps<{
  projectId: string;
  filter: string;
}>();

const summary = ref("");
const loading = ref(false);
const error = ref("");

const renderedSummary = computed(() =>
  summary.value ? (marked.parse(summary.value) as string) : "",
);

async function generate() {
  if (!props.projectId) return;
  loading.value = true;
  error.value = "";
  summary.value = "";
  try {
    summary.value = await fetchSummary(props.projectId, props.filter);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <button
      class="self-start px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold text-sm hover:bg-indigo-700 active:bg-indigo-800 disabled:opacity-50 transition-colors"
      :disabled="loading || !projectId"
      @click="generate"
    >
      <span v-if="loading" class="inline-flex items-center gap-2">
        <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="4"
          />
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8v8H4z"
          />
        </svg>
        Summarizing… (10-30 seconds)
      </span>
      <span v-else>Generate summary</span>
    </button>

    <p v-if="error" class="text-red-500 text-sm">{{ error }}</p>

    <!-- Rendered markdown -->
    <div
      v-if="renderedSummary"
      class="prose prose-slate max-w-none p-4 rounded-xl bg-slate-50 border border-slate-200"
      v-html="renderedSummary"
    />

    <p v-else-if="!loading" class="text-slate-400 text-sm italic">
      Click "Generate summary" to produce an AI-powered synthesis of all
      conversations in this project.
    </p>
  </div>
</template>
