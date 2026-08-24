import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replaceAll('\\', '/')
          if (!moduleId.includes('/node_modules/')) return undefined
          if (/\/node_modules\/(react|react-dom|scheduler)\//.test(moduleId)) return 'react-vendor'
          if (moduleId.includes('/node_modules/@ant-design/icons')) return 'ant-icons'
          if (moduleId.includes('/node_modules/antd/')) return 'antd'
          if (moduleId.includes('/node_modules/@rc-component/') || /\/node_modules\/rc-[^/]+\//.test(moduleId)) return 'antd-components'
          if (moduleId.includes('/node_modules/@tanstack/') || moduleId.includes('/node_modules/react-router')) return 'app-vendor'
          if (moduleId.includes('/node_modules/lucide-react/')) return 'lucide-icons'
          return 'antd-components'
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
