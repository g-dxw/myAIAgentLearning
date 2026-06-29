const API_BASE = '/api/v1';

let currentConversationId = null;
let isStreaming = false;
let docPollTimer = null;

// ─── 初始化 ───
document.addEventListener('DOMContentLoaded', () => {
    loadDocuments();
    loadConversations();

    document.getElementById('fileInput').addEventListener('change', (e) => {
        const file = e.target.files[0];
        document.getElementById('fileName').textContent = file ? file.name : '';
        document.getElementById('uploadBtn').disabled = !file;
    });
});

// ─── 文档管理 ───
async function loadDocuments() {
    try {
        const res = await fetch(`${API_BASE}/documents/`);
        const data = await res.json();
        if (data.success) {
            renderDocuments(data.data.items);
            document.getElementById('docCount').textContent = `共 ${data.data.total} 份文档`;
            // 如果有正在处理的文档，启动轮询
            const hasProcessing = data.data.items.some(d => d.status === 'pending' || d.status === 'processing');
            if (hasProcessing) {
                startDocPolling();
            }
        }
    } catch (e) {
        showError('加载文档列表失败');
    }
}

function renderDocuments(docs) {
    const list = document.getElementById('docList');
    list.innerHTML = '';
    docs.forEach(doc => {
        const li = document.createElement('li');
        const statusTag = getStatusTag(doc.status, doc.chunk_count, doc.error_msg);
        li.innerHTML = `
            <div class="doc-name">
                <span>${getFileIcon(doc.file_type)}</span>
                <span title="${doc.filename}">${doc.filename}</span>
                ${statusTag}
            </div>
            <button class="btn btn-danger" onclick="deleteDocument(${doc.id}, event)" ${doc.status === 'processing' ? 'disabled' : ''}>删除</button>
        `;
        list.appendChild(li);
    });
}

function getStatusTag(status, chunkCount, errorMsg) {
    if (status === 'pending' || status === 'processing') {
        return `<span class="status-tag processing"><span class="loading-sm"></span>处理中</span>`;
    }
    if (status === 'done') {
        return `<span class="status-tag done">${chunkCount} 片段</span>`;
    }
    if (status === 'error') {
        return `<span class="status-tag error" title="${errorMsg || '处理失败'}">失败</span>`;
    }
    return '';
}

function getFileIcon(ext) {
    if (ext === '.pdf') return '📕';
    if (ext === '.md') return '📝';
    if (ext === '.txt') return '📄';
    if (ext === '.html') return '🌐';
    return '📎';
}

// 轮询文档状态
function startDocPolling() {
    if (docPollTimer) return;
    docPollTimer = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/documents/`);
            const data = await res.json();
            if (data.success) {
                const items = data.data.items;
                const hasProcessing = items.some(d => d.status === 'pending' || d.status === 'processing');
                renderDocuments(items);
                document.getElementById('docCount').textContent = `共 ${data.data.total} 份文档`;

                // 检查是否有刚完成或刚失败的文档
                items.forEach(d => {
                    if (d.status === 'done') showSuccess(`${d.filename} Embedding 完成（${d.chunk_count} 片段）`);
                    if (d.status === 'error') showError(`${d.filename} 处理失败：${d.error_msg || '未知错误'}`);
                });

                if (!hasProcessing) {
                    stopDocPolling();
                }
            }
        } catch (e) { /* ignore */ }
    }, 2000);
}

function stopDocPolling() {
    if (docPollTimer) {
        clearInterval(docPollTimer);
        docPollTimer = null;
    }
}

async function uploadFile() {
    const input = document.getElementById('fileInput');
    const file = input.files[0];
    if (!file) return;

    const btn = document.getElementById('uploadBtn');
    btn.disabled = true;
    btn.textContent = '上传中...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`${API_BASE}/documents/`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showSuccess(`文件已上传，正在后台处理：${data.data.filename}`);
            input.value = '';
            document.getElementById('fileName').textContent = '';
            loadDocuments();
        } else {
            showError(data.error || '上传失败');
        }
    } catch (e) {
        showError('上传请求失败');
    } finally {
        btn.disabled = true;
        btn.textContent = '上传';
    }
}

async function deleteDocument(id, event) {
    event.stopPropagation();
    if (!confirm('确定要删除这个文档吗？')) return;

    try {
        const res = await fetch(`${API_BASE}/documents/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            loadDocuments();
        } else {
            showError(data.error || '删除失败');
        }
    } catch (e) {
        showError('删除请求失败');
    }
}

// ─── 对话管理 ───
async function loadConversations() {
    try {
        const res = await fetch(`${API_BASE}/conversations/`);
        const data = await res.json();
        if (data.success) {
            renderConversations(data.data);
        }
    } catch (e) {
        showError('加载对话列表失败');
    }
}

function renderConversations(convs) {
    const list = document.getElementById('convList');
    list.innerHTML = '';
    convs.forEach(conv => {
        const li = document.createElement('li');
        li.className = conv.id === currentConversationId ? 'active' : '';
        li.innerHTML = `<span>${conv.title}</span>`;
        li.onclick = () => selectConversation(conv.id);
        list.appendChild(li);
    });
}

async function createConversation() {
    try {
        const res = await fetch(`${API_BASE}/conversations/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: '新对话' })
        });
        const data = await res.json();
        if (data.success) {
            currentConversationId = data.data.id;
            loadConversations();
            clearChat();
        }
    } catch (e) {
        showError('创建对话失败');
    }
}

async function selectConversation(id) {
    currentConversationId = id;
    renderConversations(await fetchConversations());
    loadMessages(id);
}

async function fetchConversations() {
    const res = await fetch(`${API_BASE}/conversations/`);
    const data = await res.json();
    return data.success ? data.data : [];
}

async function loadMessages(convId) {
    try {
        const res = await fetch(`${API_BASE}/conversations/${convId}/messages`);
        const data = await res.json();
        if (data.success) {
            clearChat();
            const chatArea = document.getElementById('chatArea');
            data.data.forEach(msg => {
                const sources = msg.sources ? JSON.parse(msg.sources) : null;
                const div = appendMessage(msg.role, msg.content, sources, true);
                if (sources && sources.length > 0) {
                    renderSources(div, sources);
                }
            });
        }
    } catch (e) {
        showError('加载消息失败');
    }
}

function clearChat() {
    const chatArea = document.getElementById('chatArea');
    chatArea.innerHTML = '';
}

// ─── 问答 ───
async function sendQuestion() {
    if (isStreaming) return;

    const input = document.getElementById('questionInput');
    const question = input.value.trim();
    if (!question) return;

    input.value = '';
    appendMessage('user', question, null, true);

    const streamToggle = document.getElementById('streamToggle').checked;

    if (streamToggle) {
        await sendStream(question);
    } else {
        await sendNormal(question);
    }
}

async function sendNormal(question) {
    const assistantDiv = appendMessage('assistant', '<span class="loading"></span>', null, true);

    try {
        const res = await fetch(`${API_BASE}/qa/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                conversation_id: currentConversationId
            })
        });
        const data = await res.json();
        if (data.success) {
            updateMessage(assistantDiv, data.data.answer, data.data.sources);
        } else {
            updateMessage(assistantDiv, `❌ ${data.error || '请求失败'}`, null);
        }
    } catch (e) {
        updateMessage(assistantDiv, '❌ 网络请求失败', null);
    }
}

async function sendStream(question) {
    isStreaming = true;
    const assistantDiv = appendMessage('assistant', '', null, true);
    const contentDiv = assistantDiv.querySelector('.message-content');
    let fullText = '';
    let sources = null;

    try {
        const res = await fetch(`${API_BASE}/qa/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                conversation_id: currentConversationId
            })
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                const eventLine = line.trim();
                if (!eventLine.startsWith('event: message')) continue;

                const dataMatch = eventLine.match(/data: (.+)/);
                if (!dataMatch) continue;

                try {
                    const chunk = JSON.parse(dataMatch[1]);
                    if (chunk.error) {
                        contentDiv.textContent = `❌ ${chunk.error}`;
                        isStreaming = false;
                        return;
                    }
                    if (chunk.delta) {
                        fullText += chunk.delta;
                        contentDiv.textContent = fullText;
                        scrollToBottom();
                    }
                    if (chunk.done) {
                        sources = chunk.sources || sources;
                    }
                } catch (e) {
                    // ignore parse error
                }
            }
        }

        // 流结束后渲染来源
        if (sources && sources.length > 0) {
            renderSources(assistantDiv, sources);
        }
    } catch (e) {
        contentDiv.textContent = '❌ 网络请求失败';
    } finally {
        isStreaming = false;
    }
}

// ─── UI 辅助 ───
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function appendMessage(role, content, sources, appendToChat = true) {
    const chatArea = document.getElementById('chatArea');
    const div = document.createElement('div');
    div.className = `message ${role}`;

    const roleLabel = role === 'user' ? '你' : 'AI';
    const safeContent = escapeHtml(content);
    div.innerHTML = `
        <div class="message-role">${roleLabel}</div>
        <div class="message-content">${safeContent}</div>
    `;

    if (appendToChat) {
        chatArea.appendChild(div);
        scrollToBottom();
    }

    return div;
}

function updateMessage(div, content, sources) {
    const contentDiv = div.querySelector('.message-content');
    contentDiv.innerHTML = '';
    contentDiv.innerHTML = escapeHtml(content);

    if (sources && sources.length > 0) {
        renderSources(div, sources);
    }
    scrollToBottom();
}

function renderSources(messageDiv, sources) {
    let sourcesDiv = messageDiv.querySelector('.sources');
    if (!sourcesDiv) {
        sourcesDiv = document.createElement('div');
        sourcesDiv.className = 'sources';
        messageDiv.appendChild(sourcesDiv);
    }

    let html = '<div class="sources-title">📎 来源引用</div>';
    sources.forEach((src, i) => {
        const meta = src.metadata || {};
        const metaStr = Object.entries(meta)
            .filter(([k]) => k !== 'doc_id')
            .map(([k, v]) => `${k}: ${v}`)
            .join(' | ');
        html += `
            <div class="source-item">
                <div class="source-meta">[${i + 1}] ${metaStr}</div>
                <div class="source-text">${src.text || ''}</div>
            </div>
        `;
    });
    sourcesDiv.innerHTML = html;
}

function scrollToBottom() {
    const chatArea = document.getElementById('chatArea');
    chatArea.scrollTop = chatArea.scrollHeight;
}

function showError(msg) {
    showToast(msg, '#dc2626');
}

function showSuccess(msg) {
    showToast(msg, '#16a34a');
}

function showToast(msg, bgColor) {
    const toast = document.createElement('div');
    toast.className = 'error-toast';
    toast.style.background = bgColor;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
