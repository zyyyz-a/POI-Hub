import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'happy-dom',
    setupFiles: './tests/setup.ts',
    globals: true,
    css: true,
    maxWorkers: 1,
    fileParallelism: false,
    include: ['tests/**/*.{test,spec}.{js,ts,jsx,tsx}'],
  },
})
