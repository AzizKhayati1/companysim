import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  toolsUsed?: string[];
}

const SUGGESTIONS = [
  "Which department has the highest burnout?",
  "Who are my top at-risk employees?",
  "What if we gave retention bonuses?",
];

const GREETING: DisplayMessage = {
  role: "assistant",
  content: "Hi — I can answer questions about your workforce data. Ask me anything, or try a suggestion below.",
};

export default function AskVantageWidget({ orgId }: { orgId: number }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<DisplayMessage[]>([GREETING]);
  const [input, setInput] = useState("");
  const [notConfigured, setNotConfigured] = useState(false);

  const sendMutation = useMutation({
    mutationFn: (message: string) =>
      api.askOrgChat(
        orgId, message,
        messages
          .filter((m) => m !== GREETING)
          .map((m) => ({ role: m.role, content: m.content })),
      ),
    onSuccess: (resp, message) => {
      setMessages((prev) => [
        ...prev,
        { role: "user", content: message },
        { role: "assistant", content: resp.reply, toolsUsed: resp.tools_used },
      ]);
      if (!resp.llm_available) setNotConfigured(true);
    },
  });

  const handleSend = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sendMutation.isPending) return;
    sendMutation.mutate(trimmed);
    setInput("");
  };

  if (!open) {
    return (
      <div className="ask-vantage-button" onClick={() => setOpen(true)}>
        <svg width="19" height="19" viewBox="0 0 20 20">
          <path
            d="M3 5.5A2.5 2.5 0 0 1 5.5 3h9A2.5 2.5 0 0 1 17 5.5v6A2.5 2.5 0 0 1 14.5 14H8l-4 3.2V14H5.5A2.5 2.5 0 0 1 3 11.5z"
            fill="currentColor"
          />
        </svg>
        <span>Ask Vantage</span>
      </div>
    );
  }

  return (
    <div className="ask-vantage-panel">
      <div className="ask-vantage-header">
        <div className="ask-vantage-header-mark" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="ask-vantage-header-title">Ask Vantage</div>
          <div className="ask-vantage-header-subtitle">Grounded in your workforce data</div>
        </div>
        <div className="ask-vantage-close" onClick={() => setOpen(false)}>
          <svg width="12" height="12" viewBox="0 0 20 20">
            <line x1="3" y1="3" x2="17" y2="17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <line x1="17" y1="3" x2="3" y2="17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </div>
      </div>

      <div className="ask-vantage-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-message chat-message-${m.role}`}>
            <div className="chat-bubble">{m.content}</div>
            {m.role === "assistant" && m.toolsUsed && m.toolsUsed.length > 0 && (
              <div className="chat-tools-used">Checked: {m.toolsUsed.join(", ")}</div>
            )}
          </div>
        ))}
        {sendMutation.isPending && (
          <div className="chat-message chat-message-assistant">
            <div className="chat-bubble">Thinking…</div>
          </div>
        )}
        {notConfigured && (
          // The server's reply already carries the specific reason (which
          // provider is active and what it is missing). Repeating a fixed
          // checklist here would contradict it the moment the deployment
          // uses the other provider.
          <p className="muted" style={{ fontSize: 11.5, margin: 0 }}>
            Needs <code>COMPANYSIM_LLM_CHAT=1</code> and a configured LLM provider —
            see <code>GET /llm/status</code> for what this server resolved.
          </p>
        )}
      </div>

      <div className="ask-vantage-footer">
        <div className="ask-vantage-suggestions">
          {SUGGESTIONS.map((s) => (
            <div key={s} className="ask-vantage-suggestion" onClick={() => handleSend(s)}>
              {s}
            </div>
          ))}
        </div>
        <div className="ask-vantage-input-row">
          <input
            placeholder="Ask about your workforce…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSend(input);
            }}
            disabled={sendMutation.isPending}
          />
          <div className="ask-vantage-send" onClick={() => handleSend(input)}>
            <svg width="15" height="15" viewBox="0 0 20 20">
              <path
                d="M3 10h11M9.5 5l5 5-5 5"
                fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}
