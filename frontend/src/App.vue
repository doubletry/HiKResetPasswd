<template>
  <div id="app">
    <header class="app-header">
      <h1>🔐 海康威视密码重置工具</h1>
      <p class="subtitle">Hikvision Camera Password Reset Tool</p>
    </header>
    <main class="app-main">
      <HikResetTool />
    </main>
    <footer class="app-footer">
      <p>用于车间内海康威视摄像头密码重置 | For authorized personnel only</p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import HikResetTool from './components/HikResetTool.vue'
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif;
  background: #f0f2f5;
  color: #333;
  min-height: 100vh;
}

#app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);
  color: white;
  padding: 20px 24px;
  text-align: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.app-header h1 {
  font-size: 1.8rem;
  font-weight: 600;
  margin-bottom: 4px;
}

.subtitle {
  font-size: 0.9rem;
  opacity: 0.85;
}

.app-main {
  flex: 1;
  padding: 24px 16px;
  max-width: 960px;
  margin: 0 auto;
  width: 100%;
}

.app-footer {
  background: #333;
  color: #aaa;
  text-align: center;
  padding: 12px;
  font-size: 0.8rem;
}
</style>
