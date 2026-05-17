// ==================== 状态管理 ====================
let chats = JSON.parse(localStorage.getItem('chats')) || [];
let currentChatId = localStorage.getItem('currentChatId') || null;
let isStreaming = false;

// DOM
const chatListEl = document.getElementById('chatList');
const messageListEl = document.getElementById('messageList');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const newChatBtn = document.getElementById('newChatBtn');
const clearBtn = document.getElementById('clearBtn');

// 初始化
init();

function init() {
  if (chats.length === 0) createNewChat();
  if (!currentChatId || !chats.find(c => c.id === currentChatId)) {
    currentChatId = chats[0]?.id;
  }
  renderChatList();
  loadCurrentChat();
}

// ==================== 对话管理 ====================
function createNewChat() {
  const id = 'chat_' + Date.now();
  chats.unshift({ id, title: '新对话', messages: [] });
  currentChatId = id;
  saveToLocal();
  renderChatList();
  loadCurrentChat();
}

function switchChat(id) {
  currentChatId = id;
  localStorage.setItem('currentChatId', id);
  renderChatList();
  loadCurrentChat();
}

function deleteChat(id, e) {
  e.stopPropagation();
  if (chats.length <= 1) return alert('至少保留一个对话');
  chats = chats.filter(c => c.id !== id);
  if (currentChatId === id) {
    currentChatId = chats[0].id;
    localStorage.setItem('currentChatId', currentChatId);
  }
  saveToLocal();
  renderChatList();
  loadCurrentChat();
}

// ==================== 渲染 ====================
function renderChatList() {
  chatListEl.innerHTML = '';
  chats.forEach(chat => {
    const div = document.createElement('div');
    div.className = `chat-item ${chat.id === currentChatId ? 'active' : ''}`;
    div.innerText = chat.title;
    div.onclick = () => switchChat(chat.id);

    const del = document.createElement('span');
    del.className = 'del';
    del.innerText = '删除';
    del.onclick = (e) => deleteChat(chat.id, e);
    div.appendChild(del);
    chatListEl.appendChild(div);
  });
}

function loadCurrentChat() {
  const chat = chats.find(c => c.id === currentChatId);
  messageListEl.innerHTML = '';
  chat?.messages.forEach(msg => addMessageToUI(msg.text, msg.role));
}

function addMessageToUI(text, role) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.textContent = text;
  messageListEl.appendChild(div);
  scrollToBottom();
  return div;
}

function scrollToBottom() {
  messageListEl.scrollTop = messageListEl.scrollHeight;
}

// ==================== 发送消息 + 对接你的 FastAPI SSE ====================
sendBtn.onclick = sendMessage;
userInput.onkeypress = e => e.key === 'Enter' && sendMessage();
clearBtn.onclick = clearCurrentChat;

async function sendMessage() {
  if (isStreaming) return;
  const text = userInput.value.trim();
  if (!text) return;

  const chat = chats.find(c => c.id === currentChatId);
  chat.messages.push({ role: 'user', text });

  if (chat.messages.length === 1) {
    chat.title = text.slice(0, 12) + '...';
  }

  addMessageToUI(text, 'user');
  userInput.value = '';
  saveToLocal();
  renderChatList();

  // 创建 AI 消息框
  const aiMsgEl = addMessageToUI('思考中...', 'ai');
  isStreaming = true;
  sendBtn.disabled = true;

  let fullText = '';

  try {
    // ========== 直接对接你的后端 POST /chat/stream ==========
    const response = await fetch('http://localhost:8000/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ 
        message: text,
        conversation_id: "0001"
      })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        try {
          const jsonStr = line.slice(6);
          const data = JSON.parse(jsonStr);

          // 你的后端返回格式
          if (data.content && data.text === 'text') {
            if (aiMsgEl.innerText === '思考中...') aiMsgEl.innerText = '';
            fullText += data.content;
            aiMsgEl.innerText = fullText;
            scrollToBottom();
          }

          // 结束
          if (data.type === 'done') {
            chat.messages.push({ role: 'ai', text: fullText });
            saveToLocal();
            break;
          }
        } catch (err) {}
      }
    }
  } catch (err) {
    aiMsgEl.innerText = '连接失败：' + err.message;
  } finally {
    isStreaming = false;
    sendBtn.disabled = false;
  }
}

function clearCurrentChat() {
  if (isStreaming) return alert('请等流式输出结束再清空');
  const chat = chats.find(c => c.id === currentChatId);
  chat.messages = [];
  messageListEl.innerHTML = '';
  saveToLocal();
}

// ==================== 存储 ====================
function saveToLocal() {
  localStorage.setItem('chats', JSON.stringify(chats));
}