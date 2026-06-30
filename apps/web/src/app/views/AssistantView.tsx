import React, { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { Bot, Send, Loader2 } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { useAppContext } from '../context/AppContext';
import { api, type ChatMessage } from '../services/api';
import { toast } from 'sonner';

export function AssistantView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const t = {
    title: { fa: 'دستیار هوشمند', en: 'Smart Assistant' },
    placeholder: { fa: 'سوال خود را بنویسید...', en: 'Type your question...' },
    empty: {
      fa: 'درباره بازار طلا، ارز و رمزارز بپرسید',
      en: 'Ask about gold, currency and crypto markets'
    },
    sendFail: { fa: 'پاسخ در دسترس نیست', en: 'Reply is unavailable' }
  };

  useEffect(() => {
    // Keep the newest message in view as the conversation grows.
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, isSending]);

  const handleSend = async () => {
    const text = draft.trim();
    if (!text || isSending) return;

    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content: text }];
    setMessages(nextMessages);
    setDraft('');
    setIsSending(true);
    try {
      const result = await api.insights.chat(nextMessages, language);
      setMessages((prev) => [...prev, { role: 'assistant', content: result.reply }]);
    } catch (error) {
      const message = error instanceof Error ? error.message : t.sendFail[language];
      toast.error(message);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="h-full flex flex-col space-y-6">
      <div className="flex items-center justify-between">
        <h1 className={`text-3xl font-bold ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
          {t.title[language]}
        </h1>
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#D4AF37] text-black">
          <Bot size={22} />
        </div>
      </div>

      <Card className={`flex flex-1 flex-col min-h-0 ${isDark ? 'bg-[#0E0E0E]/60 border-white/5' : 'bg-white/60 border-black/5'}`}>
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <Bot size={48} className={`mx-auto mb-4 ${isDark ? 'text-gray-600' : 'text-gray-400'}`} />
                <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>{t.empty[language]}</p>
              </div>
            </div>
          ) : (
            messages.map((msg, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[78%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap leading-7 ${
                    msg.role === 'user'
                      ? 'bg-[#D4AF37] text-black'
                      : isDark ? 'bg-[#1A1A1A] text-white' : 'bg-gray-100 text-[#3B2E13]'
                  }`}
                >
                  {msg.content}
                </div>
              </motion.div>
            ))
          )}

          {isSending && (
            <div className="flex justify-start">
              <div className={`rounded-2xl px-4 py-3 ${isDark ? 'bg-[#1A1A1A]' : 'bg-gray-100'}`}>
                <Loader2 size={18} className={`animate-spin ${isDark ? 'text-[#D4AF37]' : 'text-[#9D7A20]'}`} />
              </div>
            </div>
          )}
        </div>

        <div className={`p-4 border-t ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <div className="flex gap-2">
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={t.placeholder[language]}
              className={`flex-1 ${isDark ? 'bg-[#141414] border-[#D4AF37]/20' : 'bg-white border-[#D4AF37]/30'}`}
            />
            <Button onClick={handleSend} disabled={isSending || !draft.trim()} className="bg-[#D4AF37] text-black disabled:opacity-50">
              {isSending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
