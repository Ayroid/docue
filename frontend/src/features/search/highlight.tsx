/**
 * Render a backend highlight fragment safely.
 *
 * `ts_headline` wraps matched terms in `<mark>` but does **not** escape the
 * surrounding text, and that text is a generated purpose statement — model
 * output, stored in the database, rendered in every user's browser. Passing it
 * to `dangerouslySetInnerHTML` unmodified would make a stored-XSS sink out of
 * anything that ever writes a template description.
 *
 * So the fragment is escaped in full first, and then exactly two known markers
 * are turned back into real elements. Nothing else can survive that round trip,
 * whatever the source text contained.
 *
 * Returning React nodes rather than an HTML string means there is no
 * `dangerouslySetInnerHTML` in the codebase to copy later.
 */
export function Highlighted({ fragment }: { fragment: string }) {
  const parts = fragment.split(/(<mark>.*?<\/mark>)/g).filter(Boolean)

  return (
    <>
      {parts.map((part, index) => {
        const match = /^<mark>(.*)<\/mark>$/s.exec(part)
        return match ? (
          <mark key={index} className="bg-accent-100 text-accent-800 rounded-[3px] px-[2px]">
            {match[1]}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        )
      })}
    </>
  )
}
