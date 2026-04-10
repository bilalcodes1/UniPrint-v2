import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		port: 3000,
		proxy: {
			'/api': {
				target: 'http://localhost:5001',
				changeOrigin: true
			},
			'/socket.io': {
				target: 'http://localhost:5001',
				changeOrigin: true,
				ws: true
			}
		}
	}
});
