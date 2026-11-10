import { ReactNode, useEffect, useRef, useState } from "react";
import { t } from "../i18n";

/** 读取 / 处理中的旋转图示。放在文字旁边；屏幕阅读器读旁边的文字，图示本身隐藏。 */
export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="spinner" aria-hidden="true" style={{ width: size, height: size }} />;
}

/** 整块读取中：图示 + 文字。 */
export function Loading({ text = t("读取中…"), className = "" }: { text?: string; className?: string }) {
  return (
    <div className={`muted loading-line ${className}`} role="status">
      <Spinner size={16} />
      {text}
    </div>
  );
}

/** 分段切换：同一时间只选一项。 */
export function Seg<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="tablist" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="tab" aria-selected={value === o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** 弹出面板的开关：点外面或按 Esc 关闭。ref 放在包住按钮和面板的元素上。 */
export function usePopover<T extends string>() {
  const [open, setOpen] = useState<T | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(null);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const toggle = (name: T) => setOpen((cur) => (cur === name ? null : name));
  return { open, setOpen, toggle, ref };
}

/** 需要确认的按钮（删除、登出）：在页面里显示确认，不用浏览器的 confirm()。
 * 内置浏览器窗格等环境会直接吞掉 confirm()，按了就像没反应。 */
export function ConfirmButton({
  children,
  message,
  confirmLabel = t("确定删除"),
  onConfirm,
  className = "",
  disabled,
}: {
  children: ReactNode;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  className?: string;
  disabled?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking)
    return (
      <button type="button" className={className} disabled={disabled} onClick={() => setAsking(true)}>
        {children}
      </button>
    );
  return (
    <span className="confirm-inline" role="alertdialog" aria-label={message}>
      <span>{message}</span>
      <button
        type="button"
        className="danger-solid"
        autoFocus
        onClick={async () => {
          setAsking(false);
          await onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button type="button" onClick={() => setAsking(false)}>
        {t("取消")}
      </button>
    </span>
  );
}
