import type { HTMLAttributes, ReactNode } from "react";
import { clsx } from "clsx";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx(
        "rounded-lg border border-slate-200 bg-white shadow-sm",
        className,
      )}
      {...rest}
    />
  );
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "flex items-start justify-between border-b border-slate-200 bg-white px-6 py-4",
        className,
      )}
    >
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {description && (
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("p-6", className)} {...rest} />;
}
