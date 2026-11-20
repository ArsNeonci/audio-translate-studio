import { useId, type ReactNode } from "react";

/** One feature of a form as one bordered card: its name (20 px), a short description (14 px) and its fields.
 *  Studio, Tools and Reprocess build every form from these cards so that the spacing and the three text sizes are the same everywhere (app/forms.css). */
export default function FormSection({ title, description, step, children }: { title: string; description?: ReactNode; step?: number; children: ReactNode }) {
  const id = useId();
  return <section className="fsec" aria-labelledby={id}>
    <header className="fsec-head">
      <h3 id={id} className="fsec-title">{step !== undefined && <span className="fsec-no" aria-hidden="true">{step}</span>}{title}</h3>
      {description && <p className="fsec-desc">{description}</p>}
    </header>
    <div className="fsec-body">{children}</div>
  </section>;
}

/** The cards of one form, equally spaced. */
export function FormStack({ children }: { children: ReactNode }) {
  return <div className="fk-stack">{children}</div>;
}
