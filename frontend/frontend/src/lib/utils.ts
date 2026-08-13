import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * FNV-1a. Small, synchronous and stable across reloads — enough to key a
 * render cache on `base_version_id + change_spec` without pulling in a crypto
 * dependency or making the hot path async.
 */
export function hash(input: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

export const extOf = (fmt: string) => (fmt === 'XLS' ? '.xlsx' : fmt === 'PPT' ? '.pptx' : '.docx')

export const initialsOf = (name: string) =>
  name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
