<template>
  <section class="page" data-module="targetsite">
    <header class="page-head">
      <div>
        <h2>采集目标管理</h2>
        <p class="page-desc">维护采集目标站点的入口、协议约束和字符编码配置。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记目标站点</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出采集目标清单</button>
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
            <button class="link" type="button" :data-testid="`action-${row.id}-准入检查`" @click="checkFromRow(row)">
              准入检查
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采集目标数据，可先登记目标站点</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记目标站点</h3>
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

    <section class="panel" data-testid="admission-panel">
      <header class="panel-head">
        <div>
          <h3>目标站点准入检查</h3>
          <p class="page-desc">
            对入口URL、字符编码、抓取间隔与请求头模板做统一核验，核验通过方可进入采集；
            同一入口URL仅保留一条有效准入记录，重复检查只更新检查时间。
          </p>
        </div>
        <span class="panel-badge" data-testid="admitted-count">有效准入记录 {{ admittedCount }} 条</span>
      </header>
      <div class="admission-controls">
        <label class="control-item">
          <span>目标站点</span>
          <select v-model="selectedSiteId" data-testid="admission-site">
            <option value="" disabled>请选择要检查的目标站点</option>
            <option v-for="site in rows" :key="String(site.id)" :value="site.id">
              {{ site.站点名称 }}（{{ site.站点编号 }}）
            </option>
          </select>
        </label>
        <label class="control-item">
          <span>重定向URL（可选）</span>
          <input v-model="redirectUrl" data-testid="admission-redirect" placeholder="检查时观测到的重定向地址" />
        </label>
        <label class="control-item">
          <span>检测编码（可选）</span>
          <input v-model="detectedEncoding" data-testid="admission-encoding" placeholder="检查时观测到的实际编码" />
        </label>
        <button class="btn primary" data-testid="run-admission" type="button" :disabled="checking" @click="runAdmissionCheck">
          {{ checking ? '检查中…' : '发起准入检查' }}
        </button>
      </div>
      <p v-if="admissionMessage" class="admission-message" data-testid="admission-message">{{ admissionMessage }}</p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in admissionColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in admissions" :key="String(item.id)" :data-testid="`admission-${item.id}`" :data-conclusion="String(item.检查结论)">
            <td v-for="column in admissionColumns" :key="column">{{ item[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!admissions.length">
            <td :colspan="admissionColumns.length" class="empty-state">暂无准入记录，选择目标站点后发起准入检查</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集目标记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/targetsite'
const columns = ["站点编号", "站点名称", "入口URL", "请求方法", "请求头模板", "字符编码", "重试上限", "抓取间隔"]
const actions = ["提交校验", "启用配置", "停用配置"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const metricNames = ["目标站点总数", "待校验目标站点", "已启用目标站点"]

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

// 目标站点准入数据集：字段名与后端返回结构保持一致
const admissionColumns = ["准入编号", "站点编号", "入口URL", "字符编码", "请求头模板", "抓取间隔", "约束来源", "检查结论", "检查时间"]
const admissions = ref<Row[]>([])
const selectedSiteId = ref<number | ''>('')
const redirectUrl = ref('')
const detectedEncoding = ref('')
const checking = ref(false)
const admissionMessage = ref('')
const admittedCount = computed(() => admissions.value.filter((item) => item.检查结论 === '已准入').length)

async function loadAdmissions() {
  try {
    const response = await request(`${ENDPOINT}/admissions?size=200`)
    if (!response.ok) throw new Error('准入数据集读取失败')
    const payload = await response.json()
    admissions.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '准入数据集读取失败'
  }
}

async function runAdmissionCheck() {
  if (!selectedSiteId.value) {
    admissionMessage.value = '请先选择要检查的目标站点'
    return
  }
  checking.value = true
  admissionMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${selectedSiteId.value}/admission/check`, {
      method: 'POST',
      body: JSON.stringify({ 重定向URL: redirectUrl.value, 检测编码: detectedEncoding.value }),
    })
    const payload = await response.json()
    admissionMessage.value = payload.message || '准入检查已完成'
    await loadAdmissions()
  } catch (error) {
    admissionMessage.value = error instanceof Error ? error.message : '准入检查请求失败'
  } finally {
    checking.value = false
  }
}

function checkFromRow(row: Row) {
  selectedSiteId.value = Number(row.id)
  void runAdmissionCheck()
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
    link.download = 'targetsite.csv'
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
      throw new Error('采集目标动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集目标操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('目标站点列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集目标列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadAdmissions()
})
</script>
