import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

/**
 * An overlay for content that answers a question you just asked.
 *
 * The diagnosis is the case for it: you press Diagnose, and the answer
 * used to append itself far below a form you were already scrolled into
 * the middle of. Nothing told you it had arrived. A report you asked for
 * a second ago should arrive in front of you, and leave without a trace
 * when you dismiss it — the scenario underneath is unchanged either way.
 *
 * Kept deliberately small: a backdrop, Escape, a titled surface. Anything
 * that needs to persist after dismissal does not belong in a modal.
 */
export default function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const surfaceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);

    // Without this the page behind scrolls under the overlay, which reads
    // as the modal itself moving.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Move focus in, or a keyboard user is still tabbing the form behind.
    surfaceRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      // A click that starts inside and ends on the backdrop (a drag while
      // selecting text) must not dismiss — so only a click whose target is
      // the backdrop itself counts.
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal-surface"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={surfaceRef}
      >
        <div className="modal-head">
          <div className="modal-head-text">
            <h2 className="modal-title">{title}</h2>
            {subtitle && <p className="modal-subtitle">{subtitle}</p>}
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.9"
                 strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l8 8M14 6l-8 8" />
            </svg>
          </button>
        </div>

        <div className="modal-body">{children}</div>

        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}
