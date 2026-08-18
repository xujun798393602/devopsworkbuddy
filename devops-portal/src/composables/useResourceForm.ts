/**
 * Generic create / edit dialog form composable.
 *
 * Removes the boilerplate shared by every domain's create-or-edit dialog:
 *  - holds the editable `model` (cloned from an empty template or an existing resource),
 *  - tracks `visible` / `submitting` / `error` / `isEdit`,
 *  - on submit calls the injected `create` (or `update` when editing) callback and
 *    closes the dialog on success.
 *
 * Idempotency / `If-Match` headers are the API module's responsibility, so this
 * composable only forwards the payload (and version for edits). Components own the
 * `create`/`update` closures, keeping the composable transport-agnostic and testable.
 */
import { ref, type Ref } from 'vue';

/** Create callback. Returns the persisted resource. */
export type CreateFn<T, R> = (payload: T) => Promise<R>;

/** Update callback. Receives the edited payload and the resource version. */
export type UpdateFn<T, R> = (payload: T, version: number) => Promise<R>;

/** Options for {@link useResourceForm}. */
export interface ResourceFormOptions<T, R> {
  /** Build the blank form model for create. */
  empty: () => T;
  /** Build the form model from an existing resource for edit. */
  toResource?: (resource: R) => T;
  /** Read the optimistic-concurrency version from an existing resource. */
  versionOf?: (resource: R) => number;
  create: CreateFn<T, R>;
  update?: UpdateFn<T, R>;
}

/** Returned reactive handles + actions for {@link useResourceForm}. */
export interface UseResourceForm<T, R> {
  visible: Ref<boolean>;
  model: Ref<T>;
  editing: Ref<R | null>;
  submitting: Ref<boolean>;
  error: Ref<Error | null>;
  isEdit: Ref<boolean>;
  openCreate: () => void;
  openEdit: (resource: R) => void;
  close: () => void;
  submit: () => Promise<R | null>;
}

/** Drive a create / edit dialog bound to a typed form model. */
export function useResourceForm<T, R>(options: ResourceFormOptions<T, R>): UseResourceForm<T, R> {
  const visible = ref(false);
  const model = ref(options.empty()) as Ref<T>;
  const editing = ref<R | null>(null) as unknown as Ref<R | null>;
  const submitting = ref(false);
  const error = ref<Error | null>(null);
  const isEdit = ref(false);

  function openCreate(): void {
    editing.value = null;
    isEdit.value = false;
    model.value = options.empty();
    error.value = null;
    visible.value = true;
  }

  function openEdit(resource: R): void {
    editing.value = resource;
    isEdit.value = true;
    model.value = options.toResource ? options.toResource(resource) : (resource as unknown as T);
    error.value = null;
    visible.value = true;
  }

  function close(): void {
    visible.value = false;
  }

  async function submit(): Promise<R | null> {
    if (submitting.value) return null;
    submitting.value = true;
    error.value = null;
    try {
      const result =
        isEdit.value && editing.value && options.update && options.versionOf
          ? await options.update(model.value, options.versionOf(editing.value))
          : await options.create(model.value);
      visible.value = false;
      return result;
    } catch (e) {
      error.value = e instanceof Error ? e : new Error(String(e));
      return null;
    } finally {
      submitting.value = false;
    }
  }

  return { visible, model, editing, submitting, error, isEdit, openCreate, openEdit, close, submit };
}
