/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {
			fontFamily: {
				sans: ['IBM Plex Sans Arabic', '-apple-system', 'sans-serif'],
			},
			colors: {
				primary: '#2D6BE4',
			},
		},
	},
	plugins: [],
};
