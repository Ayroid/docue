import type { Config } from 'tailwindcss'

/**
 * Every value here points at a CSS custom property declared in
 * `src/styles/tokens.css`. Nothing is hardcoded as a hex literal — a
 * Tailwind class like `bg-accent-200` resolves through the variable and
 * picks up the Organic palette set via `data-hub-theme` on `<html>`.
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        ink: 'var(--color-text)',
        divider: 'var(--color-divider)',
        accent: {
          DEFAULT: 'var(--color-accent)',
          100: 'var(--color-accent-100)',
          200: 'var(--color-accent-200)',
          300: 'var(--color-accent-300)',
          400: 'var(--color-accent-400)',
          500: 'var(--color-accent-500)',
          600: 'var(--color-accent-600)',
          700: 'var(--color-accent-700)',
          800: 'var(--color-accent-800)',
          900: 'var(--color-accent-900)',
        },
        accent2: {
          DEFAULT: 'var(--color-accent-2)',
          100: 'var(--color-accent-2-100)',
          200: 'var(--color-accent-2-200)',
          300: 'var(--color-accent-2-300)',
          400: 'var(--color-accent-2-400)',
          500: 'var(--color-accent-2-500)',
          600: 'var(--color-accent-2-600)',
          700: 'var(--color-accent-2-700)',
          800: 'var(--color-accent-2-800)',
          900: 'var(--color-accent-2-900)',
        },
        neutral: {
          100: 'var(--color-neutral-100)',
          200: 'var(--color-neutral-200)',
          300: 'var(--color-neutral-300)',
          400: 'var(--color-neutral-400)',
          500: 'var(--color-neutral-500)',
          600: 'var(--color-neutral-600)',
          700: 'var(--color-neutral-700)',
          800: 'var(--color-neutral-800)',
          900: 'var(--color-neutral-900)',
        },
      },
      fontFamily: {
        heading: 'var(--font-heading)',
        body: 'var(--font-body)',
      },
      /* The Organic ramp is non-integer on purpose (4.4px base). Exposed as
         `p-1`..`p-8` equivalents under a `ds` prefix so they never collide with
         Tailwind's own 0.25rem scale. */
      spacing: {
        'ds-1': 'var(--space-1)',
        'ds-2': 'var(--space-2)',
        'ds-3': 'var(--space-3)',
        'ds-4': 'var(--space-4)',
        'ds-6': 'var(--space-6)',
        'ds-8': 'var(--space-8)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        /* The prototype's retune of the Organic frame. */
        control: 'var(--radius-control)',
        tag: 'var(--radius-tag)',
        card: 'var(--radius-card)',
        pill: '999px',
      },
      boxShadow: {
        'elev-sm': 'var(--shadow-sm)',
        'elev-md': 'var(--shadow-md)',
        'elev-lg': 'var(--shadow-lg)',
      },
      /* Stitch's type scale, names kept as published so the design and the
         code refer to a heading the same way. */
      fontSize: {
        'display-lg': ['48px', { lineHeight: '60px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'headline-lg': ['32px', { lineHeight: '40px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'headline-md': ['24px', { lineHeight: '32px', fontWeight: '600' }],
        'title-lg': ['18px', { lineHeight: '28px', fontWeight: '600' }],
        'body-lg': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'label-md': ['12px', { lineHeight: '16px', letterSpacing: '0.05em', fontWeight: '500' }],
        h1: ['48px', { lineHeight: '60px', letterSpacing: '-0.02em' }],
        h2: ['32px', { lineHeight: '40px', letterSpacing: '-0.01em' }],
        h3: ['24px', { lineHeight: '32px' }],
        h4: ['18px', { lineHeight: '28px' }],
        h5: ['16px', { lineHeight: '24px' }],
        h6: ['12px', { lineHeight: '16px', letterSpacing: '0.05em' }],
      },
      maxWidth: {
        container: 'var(--container-max)',
      },
      keyframes: {
        hubfade: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'none' },
        },
        hubglow: {
          from: { background: 'var(--color-accent-100)' },
          to: { background: 'transparent' },
        },
        /* A highlight travelling left-to-right across a placeholder. Moving
           `background-position` rather than a child element keeps this to one
           compositor-friendly property and means a skeleton is one div. */
        hubshimmer: {
          from: { backgroundPosition: '200% 0' },
          to: { backgroundPosition: '-200% 0' },
        },
      },
      animation: {
        hubfade: 'hubfade .35s ease both',
        'hubfade-fast': 'hubfade .3s ease both',
        hubglow: 'hubglow 2.4s ease forwards',
        hubshimmer: 'hubshimmer 1.6s linear infinite',
      },
    },
  },
  plugins: [],
} satisfies Config
