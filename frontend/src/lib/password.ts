/**
 * The password rule, mirrored from `app/core/security.py::password_problem`.
 *
 * Checked in the browser purely to answer without a round trip: the server
 * enforces the same rule and is the one that decides, so a disagreement here
 * costs a redundant 422, never a weak password getting through.
 *
 * **Length only.** There were composition rules — upper and lower case, a
 * digit — and they are gone on both sides. NIST SP 800-63B advises against
 * them: people satisfy them the same predictable way, so `Password1` passed
 * while `correct horse battery staple` was refused. Length is what resists
 * guessing.
 *
 * One file rather than a copy in `Register` and another in `ResetPassword`,
 * which is how the two would drift the next time the rule changes.
 */

export const MIN_PASSWORD_LENGTH = 8

/* bcrypt hashes at most 72 *bytes* and silently truncates past that, so the
   backend refuses anything longer rather than storing a hash that is weaker
   than the password looks. Counted in bytes here too — `length` counts UTF-16
   code units, so an emoji passphrase would pass this check and fail the
   server's. */
export const MAX_PASSWORD_BYTES = 72

/** Human-readable requirement, for the hint under the field. Exported so the
    hint and the check can never describe different rules. */
export const PASSWORD_HINT = `At least ${MIN_PASSWORD_LENGTH} characters. A short phrase works well.`

export function passwordProblem(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`
  }
  if (new TextEncoder().encode(password).length > MAX_PASSWORD_BYTES) {
    return `Password must be at most ${MAX_PASSWORD_BYTES} bytes.`
  }
  return null
}
