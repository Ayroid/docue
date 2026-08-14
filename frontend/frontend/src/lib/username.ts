/**
 * Username shaping, mirrored from `app/core/security.py`.
 *
 * The rule is letters, digits, dot, dash and underscore, 3–64 characters.
 * **`@` is excluded, and that is load-bearing rather than tidy:** `/auth/login`
 * takes a single identifier and resolves it against the email *or* the
 * username, so a username containing `@` could equal somebody else's address
 * and two accounts would answer to one login string.
 *
 * Which makes the field a trap, because the two things people naturally type
 * into it are their email address and their full name — and both are refused.
 * So the field is not validated after the fact here; it is shaped as you type,
 * and prefilled from the email, so an invalid one cannot be produced.
 */

export const MIN_USERNAME_LENGTH = 3
export const MAX_USERNAME_LENGTH = 64

export const USERNAME_HINT = 'Letters, digits, dot, dash or underscore. Leave it and we’ll use your email name.'

/**
 * Everything disallowed collapsed to a dot.
 *
 * Collapsed rather than dropped: `Riya Mehta` becomes `riya.mehta`, not
 * `riyamehta`. The word boundary is information, and deleting it makes the
 * result harder to read than what was typed.
 *
 * Leading and trailing separators are *not* trimmed here, because this runs on
 * every keystroke — trimming them would make it impossible to type `riya.` on
 * the way to `riya.mehta`. `tidyUsername` does that on submit.
 */
export function shapeUsername(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '.')
    .replace(/\.{2,}/g, '.')
    .slice(0, MAX_USERNAME_LENGTH)
}

/** `shapeUsername`, plus the edge trim that only makes sense once editing has
    stopped. */
export function tidyUsername(value: string): string {
  return shapeUsername(value).replace(/^[._-]+|[._-]+$/g, '')
}

/** A username suggested from an email address — the local part, shaped.
 *
 *  Matches `security.suggest_username`, so the prefill and the server's own
 *  fallback agree on what `riya.mehta@ymsli.com` should become. */
export function suggestUsername(email: string): string {
  return tidyUsername(email.split('@', 1)[0] ?? '')
}
