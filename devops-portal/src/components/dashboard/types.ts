/**
 * Shared view-model types for the dashboard card family.
 *
 * Kept in a plain module (not inside `<script setup>`, which cannot contain ES
 * module exports) so every card can import them without a runtime dependency.
 */

/** Semantic tone for pills/chips; maps to the tokens in src/styles/tokens.css. */
export type ChipTone = 'neutral' | 'error' | 'warn' | 'info' | 'ok';

/** Normalised row rendered by MyWorkItemCard. */
export interface DisplayItem {
  id: string;
  primary: string;
  secondary: string;
  chip?: string;
  chipTone?: ChipTone;
}
