import React, { useState } from 'react';
import { motion } from 'motion/react';
import { MessageCircle, Send, Paperclip, Upload } from 'lucide-react';
import { Card } from '@nerkhbaan/ui/app/components/ui/card';
import { Button } from '@nerkhbaan/ui/app/components/ui/button';
import { Input } from '@nerkhbaan/ui/app/components/ui/input';
import { useAppContext } from '../context/AppContext';
import { toast } from 'sonner';

type Ticket = {
  id: string;
  subject: string;
  status: 'open' | 'answered' | 'closed';
  date: string;
  lastMessage: string;
};

type Message = {
  id: string;
  from: 'user' | 'admin';
  content: string;
  timestamp: string;
};

export function SupportView() {
  const { language, theme } = useAppContext() as any;
  const isDark = theme === 'dark';

  const [tickets, setTickets] = useState<Ticket[]>([
    {
      id: '1',
      subject: language === 'fa' ? 'مشکل در دریافت قیمت طلا' : 'Issue with gold price fetching',
      status: 'open',
      date: '2025-06-20',
      lastMessage: language === 'fa' ? 'در حال بررسی...' : 'Investigating...'
    }
  ]);

  const [selectedTicket, setSelectedTicket] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      from: 'user',
      content: language === 'fa' ? 'سلام، قیمت طلا به روز نمی‌شود.' : 'Hello, gold price is not updating.',
      timestamp: '2025-06-20T10:30:00'
    },
    {
      id: '2',
      from: 'admin',
      content: language === 'fa' ? 'سلام، در حال بررسی هستیم.' : 'Hello, we are investigating.',
      timestamp: '2025-06-20T10:35:00'
    }
  ]);

  const [newMessage, setNewMessage] = useState('');
  const [newTicketSubject, setNewTicketSubject] = useState('');
  const [newTicketMessage, setNewTicketMessage] = useState('');
  const [showNewTicketForm, setShowNewTicketForm] = useState(false);

  const t = {
    title: { fa: 'پشتیبانی', en: 'Support' },
    tickets: { fa: 'تیکت‌ها', en: 'Tickets' },
    newTicket: { fa: 'تیکت جدید', en: 'New Ticket' },
    subject: { fa: 'موضوع', en: 'Subject' },
    message: { fa: 'پیام', en: 'Message' },
    send: { fa: 'ارسال', en: 'Send' },
    cancel: { fa: 'لغو', en: 'Cancel' },
    open: { fa: 'باز', en: 'Open' },
    answered: { fa: 'پاسخ داده شده', en: 'Answered' },
    closed: { fa: 'بسته شده', en: 'Closed' },
    typeMessage: { fa: 'پیام خود را بنویسید...', en: 'Type your message...' },
    attach: { fa: 'پیوست فایل', en: 'Attach file' },
    createTicket: { fa: 'ایجاد تیکت', en: 'Create Ticket' },
    ticketCreated: { fa: 'تیکت با موفقیت ایجاد شد', en: 'Ticket created successfully' },
    messageSent: { fa: 'پیام ارسال شد', en: 'Message sent' }
  };

  const handleSendMessage = () => {
    if (!newMessage.trim()) return;
    const msg: Message = {
      id: Date.now().toString(),
      from: 'user',
      content: newMessage,
      timestamp: new Date().toISOString()
    };
    setMessages([...messages, msg]);
    setNewMessage('');
    toast.success(t.messageSent[language]);
  };

  const handleCreateTicket = () => {
    if (!newTicketSubject.trim() || !newTicketMessage.trim()) return;
    const ticket: Ticket = {
      id: Date.now().toString(),
      subject: newTicketSubject,
      status: 'open',
      date: new Date().toISOString().split('T')[0],
      lastMessage: newTicketMessage
    };
    setTickets([ticket, ...tickets]);
    setNewTicketSubject('');
    setNewTicketMessage('');
    setShowNewTicketForm(false);
    toast.success(t.ticketCreated[language]);
  };

  const statusColors = {
    open: { bg: isDark ? 'bg-blue-500/10' : 'bg-blue-100', text: isDark ? 'text-blue-400' : 'text-blue-700' },
    answered: { bg: isDark ? 'bg-emerald-500/10' : 'bg-emerald-100', text: isDark ? 'text-emerald-400' : 'text-emerald-700' },
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
                <Button onClick={handleCreateTicket} className="flex-1 bg-[#D4AF37] text-black">
                  {t.createTicket[language]}
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
            {tickets.map((ticket) => (
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
                  {ticket.lastMessage}
                </div>
              </motion.button>
            ))}
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
                {messages.map((msg) => (
                  <motion.div
                    key={msg.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={`flex ${msg.from === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[70%] rounded-2xl px-4 py-3 ${
                        msg.from === 'user'
                          ? isDark ? 'bg-[#D4AF37] text-black' : 'bg-[#D4AF37] text-black'
                          : isDark ? 'bg-[#1A1A1A] text-white' : 'bg-gray-100 text-[#3B2E13]'
                      }`}
                    >
                      <p className="text-sm">{msg.content}</p>
                      <p className={`text-xs mt-1 ${msg.from === 'user' ? 'text-black/60' : isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                        {new Date(msg.timestamp).toLocaleTimeString(language === 'fa' ? 'fa-IR' : 'en-US', { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                  </motion.div>
                ))}
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
                    onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                    placeholder={t.typeMessage[language]}
                    className={`flex-1 ${isDark ? 'bg-[#141414] border-[#D4AF37]/20' : 'bg-white border-[#D4AF37]/30'}`}
                  />
                  <Button onClick={handleSendMessage} className="bg-[#D4AF37] text-black">
                    <Send size={18} />
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
