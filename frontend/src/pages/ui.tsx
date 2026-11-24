import { ReactNode, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
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
    <ToggleGroup type="single" variant="outline" tone="hi" size="sm" aria-label={label} value={value} onValueChange={(v) => v && onChange(v as T)}>
      {options.map((o) => (
        <ToggleGroupItem key={o.value} value={o.value}>
          {o.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
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
      <Button
        type="button"
        variant={className.includes("link") ? "link" : "outline"}
        size="sm"
        className={className.includes("danger") ? "text-destructive" : undefined}
        disabled={disabled}
        onClick={() => setAsking(true)}
      >
        {children}
      </Button>
    );
  return (
    <span className="confirm-inline" role="alertdialog" aria-label={message}>
      <span>{message}</span>
      <Button
        type="button"
        variant="destructive"
        size="sm"
        autoFocus
        onClick={async () => {
          setAsking(false);
          await onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={() => setAsking(false)}>
        {t("取消")}
      </Button>
    </span>
  );
}

/** 弹窗。关掉后内容留着（不卸载），再打开时搜索结果、写到一半的草稿都还在。 */
export function Modal({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (open && !d?.open) d?.showModal();
    if (!open && d?.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="modal" aria-label={title} onClose={onClose}>
      <div className="modal-head row between">
        <b>{title}</b>
        <Button type="button" variant="outline" size="sm" onClick={onClose}>
          {t("关闭")} ✕
        </Button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}
