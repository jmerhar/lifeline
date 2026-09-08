/**
 * The handful of primitives every screen is built from.
 *
 * Kept together and kept small: the interface is a table, some forms and two panels, and a
 * component library for that would be more code than the screens themselves.
 */

import { cloneElement, isValidElement, useId } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactElement,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

type ButtonTone = "primary" | "quiet" | "danger";

const tones: Record<ButtonTone, string> = {
  primary: "bg-accent text-accent-ink hover:opacity-90",
  quiet: "border border-line text-ink hover:bg-raised",
  danger: "border border-lapsed text-lapsed hover:bg-lapsed/10",
};

export function Button({
  tone = "quiet",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: ButtonTone }) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded px-3 py-1.5 text-small
        font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-50
        ${tones[tone]} ${className}`}
    />
  );
}

/**
 * A labelled control, with its hint attached as a description rather than as part of its name.
 *
 * The distinction matters: wrapping the control in a label that also contains the hint makes
 * the field's accessible name the label *and* the hint, so a screen reader announces a
 * paragraph where a name belongs. The hint is linked with aria-describedby instead, which is
 * read after the name and only when a reader asks for detail.
 */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  const id = useId();
  const described = [hint ? `${id}-hint` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="block">
      <label htmlFor={id} className="block text-small font-medium text-ink">
        {label}
      </label>
      {hint ? (
        <span id={`${id}-hint`} className="mt-0.5 block text-micro text-muted">
          {hint}
        </span>
      ) : null}
      <div className="mt-1.5">
        {isValidElement(children)
          ? cloneElement(children as ReactElement<ControlProps>, {
              id,
              ...(described ? { "aria-describedby": described } : {}),
            })
          : children}
      </div>
      {error ? (
        <span id={`${id}-error`} className="mt-1 block text-micro text-lapsed">
          {error}
        </span>
      ) : null}
    </div>
  );
}

/** What Field is able to set on the control it wraps. */
interface ControlProps {
  id?: string;
  "aria-describedby"?: string;
}

const inputClasses = `w-full rounded border border-line bg-canvas px-2.5 py-1.5 text-small
  text-ink placeholder:text-muted/70`;

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputClasses} ${className}`} />;
}

export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${inputClasses} ${className}`} />;
}

export function TextArea({
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={`${inputClasses} font-mono text-micro leading-5 ${className}`}
    />
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-line accent-accent"
      />
      <span>
        <span className="block text-small text-ink">{label}</span>
        {hint ? <span className="block text-micro text-muted">{hint}</span> : null}
      </span>
    </label>
  );
}

/**
 * Props that ask every password manager to leave a field alone.
 *
 * A field whose label or placeholder mentions a password gets treated as a credential: the
 * manager offers to fill it in, and — worse — decides the form around it is a login form and
 * offers to save one when it is submitted. Wording alone is not enough to prevent that, because
 * the heuristics also weigh a field's neighbours, so the fields say so outright.
 *
 * Four vendors, four spellings, none of which validate against the others. Deliberately not
 * applied to lifeline's own login form, which wants exactly this behaviour.
 */
export const notACredential = {
  autoComplete: "off",
  "data-bwignore": true,
  "data-1p-ignore": true,
  "data-lpignore": "true",
  "data-form-type": "other",
} as const;

export function Choice({
  checked,
  onChange,
  label,
  hint,
  disabled,
  children,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  hint?: string;
  disabled?: boolean;
  children?: ReactNode;
}) {
  return (
    <div>
      <label className={`flex items-start gap-2.5 ${disabled ? "opacity-50" : "cursor-pointer"}`}>
        <input
          type="radio"
          checked={checked}
          onChange={onChange}
          disabled={disabled}
          className="mt-0.5 h-4 w-4 border-line accent-accent"
        />
        <span>
          <span className="block text-small text-ink">{label}</span>
          {hint ? <span className="block text-micro text-muted">{hint}</span> : null}
        </span>
      </label>
      {/* Indented to the label's text, so what belongs to a choice reads as part of it. */}
      {checked && children ? <div className="mt-3 ml-6.5">{children}</div> : null}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  busy,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  /** Names what is being switched, since the control carries no visible text of its own. */
  label: string;
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={busy}
      onClick={() => onChange(!checked)}
      className={`inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
        checked ? "bg-accent" : "bg-line"
      }`}
    >
      <span
        aria-hidden="true"
        className={`h-4 w-4 rounded-full bg-canvas transition-transform ${
          checked ? "translate-x-4.5" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded border border-line bg-surface ${className}`}>{children}</div>
  );
}

/** What a screen says when it has nothing to show: an invitation, not an apology. */
export function Empty({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <p className="text-small text-muted">{title}</p>
      {action}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-6 py-12 text-small text-muted">
      <span
        aria-hidden="true"
        className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-accent"
      />
      {label}
    </div>
  );
}

/** An error worth acting on, phrased as what went wrong rather than as an apology. */
export function Problem({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded border border-lapsed/40 bg-lapsed/10 px-3 py-2 text-small text-lapsed">
      {children}
    </p>
  );
}
