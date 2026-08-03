"use client";

import { ArrowUp, Loader2 } from "lucide-react";
import { FormEvent, KeyboardEvent, useRef } from "react";

type ChatInputProps = {
  disabled?: boolean;
  sending?: boolean;
  onSend: (content: string) => void;
};

export function ChatInput({ disabled, sending, onSend }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function submit() {
    const el = textareaRef.current;
    if (!el || disabled || sending) return;
    const value = el.value.trim();
    if (!value) return;
    onSend(value);
    el.value = "";
    el.style.height = "auto";
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function handleInput() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  return (
    <div className="bg-gradient-to-t from-[#e2eaf2] via-[#e2eaf2] to-transparent px-4 pb-4 pt-2">
      <form onSubmit={handleSubmit} className="mx-auto max-w-3xl">
        <div className="relative flex items-end rounded-2xl border border-[#cfdde9] bg-[#f4f8fc] shadow-lg shadow-slate-300/30 transition focus-within:border-sky-300 focus-within:ring-4 focus-within:ring-sky-100">
          <textarea
            ref={textareaRef}
            rows={1}
            disabled={disabled || sending}
            placeholder="สอบถามสินค้า คำสั่งซื้อ การจัดส่ง หรือโปรโมชั่น..."
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            className="max-h-[200px] min-h-[52px] flex-1 resize-none bg-transparent px-4 py-3.5 text-[15px] text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={disabled || sending}
            className="m-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-400 to-blue-500 text-white shadow-md shadow-sky-200/70 transition hover:from-sky-300 hover:to-blue-400 disabled:opacity-40"
            aria-label="Send message"
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </button>
        </div>
        <p className="mt-2 text-center text-xs text-slate-400">
          AI อาจให้ข้อมูลคลาดเคลื่อนได้ — โปรดตรวจสอบรายละเอียดคำสั่งซื้อกับทางร้านอีกครั้ง
        </p>
      </form>
    </div>
  );
}
