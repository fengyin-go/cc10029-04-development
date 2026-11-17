<template>
  <section class="page" data-module="selector">
    <header class="page-head">
      <div>
        <h2>抽取规则管理</h2>
        <p class="page-desc">管理各站点的 CSS/XPath 选择器和分页策略，保证抽取结果字段完整。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记选择器规则</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出抽取规则清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" :data-testid="`action-${row.id}-建立绑定`" @click="establishBinding(row)">
              建立绑定
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无抽取规则数据，可先登记选择器规则</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记选择器规则</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <section class="panel" data-testid="binding-panel">
      <header class="panel-head">
        <div>
          <h3>站点选择器绑定记录台账</h3>
          <p class="page-desc">
            绑定关系来自目标站点准入数据集，仅引用仍处于已准入状态的站点；
            重复或并发回写的第二份结果会被拒绝。
          </p>
        </div>
        <button class="btn" data-testid="sync-bindings" type="button" :disabled="syncing" @click="syncBindings">
          {{ syncing ? '同步中…' : '从准入数据集同步绑定' }}
        </button>
      </header>
      <p v-if="bindingMessage" class="admission-message" data-testid="binding-message">{{ bindingMessage }}</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in bindingColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in bindings" :key="String(item.id)" :data-testid="`binding-${item.id}`" :data-status="String(item.status)">
            <td v-for="column in bindingColumns" :key="column">{{ item[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!bindings.length">
            <td :colspan="bindingColumns.length" class="empty-state">暂无绑定记录，可先在采集目标页通过准入检查</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条抽取规则记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/selector'
const columns = ["规则编号", "归属站点", "列表选择器", "详情选择器", "字段选择器", "分页参数", "等待条件", "字符编码"]
const actions = ["提交校验", "启用配置", "停用配置"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const metricNames = ["选择器规则总数", "待校验选择器规则", "已启用选择器规则"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

// 站点选择器绑定记录台账：字段名与后端返回结构保持一致
const bindingColumns = ["绑定编号", "规则编号", "站点编号", "站点名称", "入口URL", "准入编号", "约束来源", "绑定时间", "status"]
const bindings = ref<Row[]>([])
const bindingMessage = ref('')
const syncing = ref(false)

async function loadBindings() {
  try {
    const response = await request(`${ENDPOINT}/bindings?size=200`)
    if (!response.ok) throw new Error('绑定台账读取失败')
    const payload = await response.json()
    bindings.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '绑定台账读取失败'
  }
}

async function establishBinding(row: Row) {
  bindingMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/bindings`, { method: 'POST' })
    const payload = await response.json()
    bindingMessage.value = payload.message || '绑定操作已完成'
    await loadBindings()
  } catch (error) {
    bindingMessage.value = error instanceof Error ? error.message : '建立绑定请求失败'
  }
}

async function syncBindings() {
  syncing.value = true
  bindingMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/bindings/sync`, { method: 'POST' })
    const payload = await response.json()
    bindingMessage.value = payload.message || '同步已完成'
    await loadBindings()
  } catch (error) {
    bindingMessage.value = error instanceof Error ? error.message : '同步请求失败'
  } finally {
    syncing.value = false
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'selector.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('抽取规则动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '抽取规则操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('选择器规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '抽取规则列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadBindings()
})
</script>
