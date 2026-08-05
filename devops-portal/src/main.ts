import 'vuetify/styles';
import './styles/tokens.css';
import './styles/global.css';
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import { createVuetify } from 'vuetify';
import App from './App.vue';
import router from './router';
createApp(App).use(createPinia()).use(router).use(createVuetify({ theme: { defaultTheme: 'light' } })).mount('#app');
