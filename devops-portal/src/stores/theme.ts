import { defineStore } from 'pinia';
export type ThemePreference='light'|'dark'|'system';
export const useThemeStore=defineStore('theme',{state:()=>({preference:(localStorage.getItem('theme')??'system') as ThemePreference}),actions:{set(value:ThemePreference){this.preference=value;localStorage.setItem('theme',value);document.documentElement.dataset.theme=value}}});
