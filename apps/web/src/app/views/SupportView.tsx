import React, { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { MessageCircle, Send, Paperclip, Loader2 } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { useAppContext } from '../context/AppContext';
import { api, type SupportMessage, type SupportTicket } from '../services/api';
import { toast } from 'sonner';

export function SupportView() {
  const { language, theme } = useAppContext();
  const isDark = theme === 'dark';

  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [isLoadingTickets, setIsLoadingTickets] = useState(true);

  const [selectedTicket, setSelectedTicket] = useState<number | null>(null);
  const [messages, setMessages] = useState<SupportMessage[]>([]);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);

  const [newMessage, setNewMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [newTicketSubject, setNewTicketSubject] = useState('');
  const [newTicketMessage, setNewTicketMessage] = useState('');
  const [showNewTicketForm, setShowNewTicketForm] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  const t = {
    title: { fa: 'پشتیبانی', en: 'Support' },
    tickets: { fa: 'تیکت‌ها', en: 'Tickets' },
    newTicket: { fa: 'تیکت جدید', en: 'New Ticket' },
    subject: { fa: 'موضوع', en: 'Subject' },
    message: { fa: 'پیام', en: 'Message' },
    send: { fa: 'ارسال', en: 'Send' },
    cancel: { fa: 'لغو', en: 'Cancel' },
    open: { fa: 'باز', en: 'Open' },
    in_progress: { fa: 'در حال بررسی', en: 'In progress' },
    waiting_for_user: { fa: 'در انتظار پاسخ شما', en: 'Waiting for you' },
    answered: { fa: 'پاسخ داده شده', en: 'Answered' },
    resolved: { fa: 'حل شده', en: 'Resolved' },
    closed: { fa: 'بسته شده', en: 'Closed' },
    typeMessage: { fa: 'پیام خود را بنویسید...', en: 'Type your message...' },
    attach: { fa: 'پیوست فایل', en: 'Attach file' },
    createTicket: { fa: 'ایجاد تیکت', en: 'Create Ticket' },
    ticketCreated: { fa: 'تیکت با موفقیت ایجاد شد', en: 'Ticket created successfully' },
    messageSent: { fa: 'پیام ارسال شد', en: 'Message sent' },
    loadFail: { fa: 'خطا در بارگذاری تیکت‌ها', en: 'Failed to load tickets' },
    sendFail: { fa: 'خطا در ارسال پیام', en: 'Failed to send message' },
    createFail: { fa: 'خطا در ایجاد تیکت', en: 'Failed to create ticket' },
    noTickets: { fa: 'هنوز تیکتی ثبت نشده است', en: 'No tickets yet' }
  };

  const loadTickets = async () => {
    try {
      const data = await api.support.listTickets();
      setTickets(data);
    } catch {
      toast.error(t.loadFail[language]);
    } finally {
      setIsLoadingTickets(false);
    }
  };

  useEffect(() => {
    loadTickets();
  }, []);

  useEffect(() => {
    if (selectedTicket === null) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setIsLoadingMessages(true);
    api.support
      .listMessages(selectedTicket)
      .then((data) => {
        if (!cancelled) setMessages(data);
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingMessages(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTicket]);

  const handleSendMessage = async () => {
    if (!newMessage.trim() || selectedTicket === null || isSending) return;
    setIsSending(true);
    try {
      const sent = await api.support.sendMessage(selectedTicket, newMessage.trim());
      setMessages((prev) => [...prev, sent]);
      setNewMessage('');
      setTickets((prev) =>
        prev.map((ticket) =>
          ticket.id === selectedTicket ? { ...ticket, last_message: sent.content } : ticket
        )
      );
    } catch {
      toast.error(t.sendFail[language]);
    } finally {
      setIsSending(false);
    }
  };

  const handleCreateTicket = async () => {
    if (!newTicketSubject.trim() || !newTicketMessage.trim() || isCreating) return;
    setIsCreating(true);
    try {
      const ticket = await api.support.createTicket({
        subject: newTicketSubject.trim(),
        message: newTicketMessage.trim()
      });
      setTickets((prev) => [ticket, ...prev]);
      setNewTicketSubject('');
      setNewTicketMessage('');
      setShowNewTicketForm(false);
      setSelectedTicket(ticket.id);
      toast.success(t.ticketCreated[language]);
    } catch {
      toast.error(t.createFail[language]);
    } finally {
      setIsCreating(false);
    }
  };

  const statusColors = {
    open: { bg: isDark ? 'bg-blue-500/10' : 'bg-blue-100', text: isDark ? 'text-blue-400' : 'text-blue-700' },
    in_progress: { bg: isDark ? 'bg-amber-500/10' : 'bg-amber-100', text: isDark ? 'text-amber-400' : 'text-amber-700' },
    waiting_for_user: { bg: isDark ? 'bg-purple-500/10' : 'bg-purple-100', text: isDark ? 'text-purple-400' : 'text-purple-700' },
    answered: { bg: isDark ? 'bg-emerald-500/10' : 'bg-emerald-100', text: isDark ? 'text-emerald-400' : 'text-emerald-700' },
    resolved: { bg: isDark ? 'bg-teal-500/10' : 'bg-teal-100', text: isDark ? 'text-teal-400' : 'text-teal-700' },
    closed: { bg: isDark ? 'bg-gray-500/10' : 'bg-gray-100', text: isDark ? 'text-gray-400' : 'text-gray-700' }
  };

  return (
    <div className="h-full flex flex-col space-y-6">
      <div className="flex items-center justify-between">
        <h1 className={`text-3xl font-bold ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>{t.title[language]}</h1>
        <Button
          onClick={() => setShowNewTicketForm(!showNewTicketForm)}
          className={`gap-2 ${isDark ? 'bg-[#D4AF37] text-black' : 'bg-[#D4AF37] text-black'}`}
        >
          <MessageCircle size={18} />
          {t.newTicket[language]}
        </Button>
      </div>

      {showNewTicketForm && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
        >
          <Card className={`p-6 ${isDark ? 'bg-[#0E0E0E]/60 border-white/5' : 'bg-white/60 border-black/5'}`}>
            <div className="space-y-4">
              <div>
                <label className={`block text-sm font-semibold mb-2 ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
                  {t.subject[language]}
                </label>
                <Input
                  value={newTicketSubject}
                  onChange={(e) => setNewTicketSubject(e.target.value)}
                  placeholder={language === 'fa' ? 'موضوع تیکت' : 'Ticket subject'}
                  className={isDark ? 'bg-[#141414] border-[#D4AF37]/20' : 'bg-white border-[#D4AF37]/30'}
                />
              </div>
              <div>
                <label className={`block text-sm font-semibold mb-2 ${isDark ? 'text-[#E2D3AA]' : 'text-[#6E5317]'}`}>
                  {t.message[language]}
                </label>
                <textarea
                  value={newTicketMessage}
                  onChange={(e) => setNewTicketMessage(e.target.value)}
                  placeholder={language === 'fa' ? 'توضیحات' : 'Description'}
                  rows={4}
                  className={`w-full rounded-lg border px-3 py-2 text-sm ${
                    isDark 
                      ? 'bg-[#141414] border-[#D4AF37]/20 text-white' 
                      : 'bg-white border-[#D4AF37]/30 text-[#3B2E13]'
                  }`}
                />
              </div>
              <div className="flex gap-3">
                <Button
                  onClick={handleCreateTicket}
                  disabled={isCreating || !newTicketSubject.trim() || !newTicketMessage.trim()}
                  className="flex-1 bg-[#D4AF37] text-black disabled:opacity-50"
                >
                  {isCreating ? <Loader2 size={16} className="animate-spin" /> : t.createTicket[language]}
                </Button>
                <Button onClick={() => setShowNewTicketForm(false)} variant="outline" className="flex-1">
                  {t.cancel[language]}
                </Button>
              </div>
            </div>
          </Card>
        </motion.div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
        <Card className={`lg:col-span-1 p-4 overflow-y-auto ${isDark ? 'bg-[#0E0E0E]/60 border-white/5' : 'bg-white/60 border-black/5'}`}>
          <h2 className={`text-lg font-bold mb-4 ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>{t.tickets[language]}</h2>
          <div className="space-y-3">
            {isLoadingTickets ? (
              <div className="flex justify-center py-8">
                <Loader2 size={24} className={`animate-spin ${isDark ? 'text-[#D4AF37]' : 'text-[#9D7A20]'}`} />
              </div>
            ) : tickets.length === 0 ? (
              <p className={`py-8 text-center text-sm ${isDark ? 'text-gray-500' : 'text-gray-500'}`}>
                {t.noTickets[language]}
              </p>
            ) : (
              tickets.map((ticket) => (
              <motion.button
                key={ticket.id}
                onClick={() => setSelectedTicket(ticket.id)}
                className={`w-full text-left p-3 rounded-xl transition-all ${
                  selectedTicket === ticket.id
                    ? isDark ? 'bg-[#D4AF37]/20 border border-[#D4AF37]' : 'bg-[#D4AF37]/20 border border-[#D4AF37]'
                    : isDark ? 'bg-[#141414] hover:bg-[#1A1A1A]' : 'bg-white hover:bg-gray-50'
                }`}
                whileHover={{ scale: 1.02 }}
              >
                <div className={`font-semibold text-sm mb-1 ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                  {ticket.subject}
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${statusColors[ticket.status].bg} ${statusColors[ticket.status].text}`}>
                    {t[ticket.status][language]}
                  </span>
                  <span className={`text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>{ticket.date}</span>
                </div>
                <div className={`text-xs truncate ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                  {ticket.last_message}
                </div>
              </motion.button>
              ))
            )}
          </div>
        </Card>

        <Card className={`lg:col-span-2 flex flex-col ${isDark ? 'bg-[#0E0E0E]/60 border-white/5' : 'bg-white/60 border-black/5'}`}>
          {selectedTicket ? (
            <>
              <div className={`p-4 border-b ${isDark ? 'border-white/10' : 'border-black/10'}`}>
                <h2 className={`text-lg font-bold ${isDark ? 'text-white' : 'text-[#3B2E13]'}`}>
                  {tickets.find(t => t.id === selectedTicket)?.subject}
                </h2>
              </div>
              
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {isLoadingMessages ? (
                  <div className="flex h-full items-center justify-center">
                    <Loader2 size={24} className={`animate-spin ${isDark ? 'text-[#D4AF37]' : 'text-[#9D7A20]'}`} />
                  </div>
                ) : (
                  messages.map((msg) => (
                  <motion.div
                    key={msg.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={`flex ${msg.from_user === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[70%] rounded-2xl px-4 py-3 ${
                        msg.from_user === 'user'
                          ? isDark ? 'bg-[#D4AF37] text-black' : 'bg-[#D4AF37] text-black'
                          : isDark ? 'bg-[#1A1A1A] text-white' : 'bg-gray-100 text-[#3B2E13]'
                      }`}
                    >
                      <p className="text-sm">{msg.content}</p>
                      <p className={`text-xs mt-1 ${msg.from_user === 'user' ? 'text-black/60' : isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                        {new Date(msg.timestamp).toLocaleTimeString(language === 'fa' ? 'fa-IR' : 'en-US', { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                  </motion.div>
                  ))
                )}
              </div>

              <div className={`p-4 border-t ${isDark ? 'border-white/10' : 'border-black/10'}`}>
                <div className="flex gap-2">
                  <button
                    className={`p-2 rounded-lg transition-colors ${isDark ? 'hover:bg-[#1A1A1A]' : 'hover:bg-gray-100'}`}
                    title={t.attach[language]}
                  >
                    <Paperclip size={20} className={isDark ? 'text-gray-400' : 'text-gray-600'} />
                  </button>
                  <Input
                    value={newMessage}
                    onChange={(e) => setNewMessage(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleSendMessage();
                      }
                    }}
                    placeholder={t.typeMessage[language]}
                    className={`flex-1 ${isDark ? 'bg-[#141414] border-[#D4AF37]/20' : 'bg-white border-[#D4AF37]/30'}`}
                  />
                  <Button onClick={handleSendMessage} disabled={isSending || !newMessage.trim()} className="bg-[#D4AF37] text-black disabled:opacity-50">
                    {isSending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <MessageCircle size={48} className={`mx-auto mb-4 ${isDark ? 'text-gray-600' : 'text-gray-400'}`} />
                <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                  {language === 'fa' ? 'یک تیکت را انتخاب کنید' : 'Select a ticket to view'}
                </p>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
