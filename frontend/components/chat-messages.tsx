"use client";

import {
  Package,
  RotateCcw,
  ShoppingBag,
  Sparkles,
  Tag,
  Truck,
  User,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatMessage } from "@/lib/types";

type ChatMessagesProps = {
  messages: ChatMessage[];
  loading: boolean;
  streamStatus?: string | null;
  streamingMessageId?: string | null;
  onExampleClick?: (text: string) => void;
  examplesDisabled?: boolean;
};

const EXAMPLE_PROMPTS = [
  {
    icon: Package,
    title: "ติดตามคำสั่งซื้อ",
    text: "ขอเช็คสถานะคำสั่งซื้อของฉันหน่อย",
  },
  {
    icon: Truck,
    title: "การจัดส่ง",
    text: "ค่าส่งเท่าไหร่ และใช้เวลากี่วันถึง?",
  },
  {
    icon: RotateCcw,
    title: "คืนสินค้า / เปลี่ยนสินค้า",
    text: "อยากคืนสินค้า ต้องทำอย่างไรบ้าง?",
  },
  {
    icon: Tag,
    title: "โปรโมชั่น",
    text: "ตอนนี้มีโปรโมชั่นหรือส่วนลดอะไรบ้าง?",
  },
] as const;

function BotAvatar() {
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-400 to-blue-500 text-white shadow-md shadow-sky-200/60">
      <ShoppingBag className="h-4.5 w-4.5" />
    </div>
  );
}

function MetadataBadges({ metadata }: { metadata: ChatMessage["metadata"] }) {
  const badges: string[] = [];
  if (metadata.route_mode_label) badges.push(metadata.route_mode_label);
  else if (metadata.route_mode) badges.push(metadata.route_mode);
  if (metadata.intent) badges.push(metadata.intent);

  if (badges.length === 0 && !metadata.plan_summary && metadata.audit_log.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2 border-t border-[#dde7f0] pt-3">
      {badges.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {badges.map((badge) => (
            <span
              key={badge}
              className="rounded-full bg-sky-100 px-2.5 py-0.5 text-[11px] font-medium text-sky-700 ring-1 ring-sky-200/60"
            >
              {badge}
            </span>
          ))}
        </div>
      )}
      {metadata.route_reason && (
        <p className="text-xs text-slate-400">{metadata.route_reason}</p>
      )}
      {metadata.plan_summary && (
        <p className="text-xs text-slate-500">
          <span className="font-medium text-slate-600">Plan: </span>
          {metadata.plan_summary}
        </p>
      )}
      {metadata.audit_log.length > 0 && (
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer transition hover:text-slate-600">
            Audit log
          </summary>
          <ul className="mt-1 list-inside list-disc space-y-0.5 pl-1">
            {metadata.audit_log.map((line, i) => (
              <li key={`${line}-${i}`}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function ChatMessages({
  messages,
  loading,
  streamStatus,
  streamingMessageId,
  onExampleClick,
  examplesDisabled,
}: ChatMessagesProps) {
  if (messages.length === 0 && !loading) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 py-8 text-center">
        <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-400 to-blue-500 text-white shadow-xl shadow-sky-200/70">
          <ShoppingBag className="h-8 w-8" />
        </div>
        <h2 className="mb-2 text-2xl font-bold text-slate-800">
          สวัสดีค่ะ ยินดีให้บริการ
        </h2>
        <p className="mb-1 flex items-center justify-center gap-1.5 text-sm text-slate-500">
          <Sparkles className="h-3.5 w-3.5 text-sky-500" />
          ผู้ช่วย AI ของร้าน — สอบถามสินค้า คำสั่งซื้อ การจัดส่ง หรือโปรโมชั่นได้เลย
        </p>
        <div className="mt-8 grid w-full max-w-2xl gap-3 sm:grid-cols-2">
          {EXAMPLE_PROMPTS.map((example) => (
            <button
              key={example.title}
              type="button"
              disabled={!onExampleClick || examplesDisabled}
              onClick={() => onExampleClick?.(example.text)}
              className="group flex items-start gap-3 rounded-2xl border border-[#d3e0eb] bg-[#f2f7fb] p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md hover:shadow-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-600 transition group-hover:bg-sky-200/70">
                <example.icon className="h-4.5 w-4.5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">
                  {example.title}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">{example.text}</p>
              </div>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          const isStreaming = !isUser && msg.id === streamingMessageId;
          return (
            <div
              key={msg.id}
              className={`chat-fade-up flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}
            >
              {isUser ? (
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#cfdde9] text-slate-600">
                  <User className="h-4.5 w-4.5" />
                </div>
              ) : (
                <BotAvatar />
              )}
              <div className={`min-w-0 flex-1 ${isUser ? "text-right" : "text-left"}`}>
                <div
                  className={`inline-block max-w-full px-4 py-3 text-left text-[15px] leading-relaxed ${
                    isUser
                      ? "rounded-2xl rounded-tr-md bg-gradient-to-br from-sky-400 to-blue-500 text-white shadow-md shadow-sky-200/60"
                      : "rounded-2xl rounded-tl-md border border-[#d3e0eb] bg-[#f4f8fc] text-slate-700 shadow-sm"
                  }`}
                >
                  {isUser ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <div className="chat-markdown max-w-none overflow-x-auto">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content || (isStreaming ? " " : "")}
                      </ReactMarkdown>
                      {isStreaming && (
                        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-sky-500 align-middle" />
                      )}
                    </div>
                  )}
                  {!isUser && !isStreaming && <MetadataBadges metadata={msg.metadata} />}
                </div>
              </div>
            </div>
          );
        })}

        {loading && !streamingMessageId && (
          <div className="chat-fade-up flex gap-3">
            <BotAvatar />
            <div className="flex items-center gap-3 rounded-2xl rounded-tl-md border border-[#d3e0eb] bg-[#f4f8fc] px-4 py-3.5 shadow-sm">
              <span className="flex items-center gap-1">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </span>
              <span className="text-sm text-slate-500">
                {streamStatus ?? "กำลังประมวลผล..."}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
