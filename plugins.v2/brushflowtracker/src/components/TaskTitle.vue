<script setup>
import { ref, watch } from 'vue'
const props = defineProps({ name: { type: String, default: '未命名任务' } })
const expanded = ref(false)
watch(() => props.name, () => { expanded.value = false })
</script>

<template>
  <div class="task-title">
    <strong :class="{ 'task-title--clamped': !expanded }">{{ name || '未命名任务' }}</strong>
    <button type="button" :aria-expanded="expanded" :aria-label="`${expanded ? '收起' : '展开'}任务名称：${name}`" @click="expanded = !expanded">{{ expanded ? '收起名称' : '展开名称' }}</button>
  </div>
</template>

<style scoped>
.task-title { min-inline-size: 0; }
.task-title strong { display: block; overflow-wrap: anywhere; line-height: 1.5; }
.task-title .task-title--clamped { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.task-title button { display: block; min-block-size: 32px; padding-block: 4px; color: rgb(var(--v-theme-primary)); font: inherit; font-size: .78rem; cursor: pointer; }
.task-title button:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
</style>
