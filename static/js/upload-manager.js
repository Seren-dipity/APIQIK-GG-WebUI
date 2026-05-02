/**
 * APIQIK 历史上传图库管理组件
 */
(function () {
    console.log("🚀 APIQIK Upload Gallery v2.9 Loaded");
    // 1. 注入 CSS 样式
    const style = document.createElement('style');
    style.textContent = `
        .btn-manage-link {
            color: var(--accent);
            text-decoration: underline;
            cursor: pointer;
            font-weight: 600;
            margin-left: 4px;
            transition: opacity 0.2s;
        }
        .btn-manage-link:hover { opacity: 0.8; }
        
        #galleryModal .history-modal-content {
            width: min(850px, 95vw);
            max-height: 85vh;
            position: relative;
        }
        
        #galleryModal #closeGalleryModal {
            position: absolute;
            top: 14px;
            right: 14px;
            z-index: 10;
        }

        .gallery-modal-body {
            padding: 0;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 600px;
            max-height: calc(85vh - 60px);
        }
        .gallery-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
            gap: 16px;
            padding: 20px;
            overflow-y: auto;
            flex: 1;
        }
        @media (max-width: 600px) {
            .gallery-grid {
                grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
                gap: 10px;
                padding: 12px;
            }
        }
        .gallery-item {
            position: relative;
            aspect-ratio: 1;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border);
            background: var(--surface-primary);
            transition: all 0.2s ease;
        }
        .gallery-item:hover {
            border-color: var(--accent);
            transform: translateY(-2px);
        }
        .gallery-item img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        /* 优化交互遮罩：Flex 布局确保内容居中 */
        .gallery-item-actions {
            position: absolute;
            inset: 0;
            background: rgba(0,0,0,0.4);
            opacity: 0;
            transition: opacity 0.2s ease;
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 5;
        }
        .gallery-item:hover .gallery-item-actions { opacity: 1; }
        
        /* 垃圾桶：全透明边框风格 */
        .gallery-trash-btn {
            position: absolute !important;
            top: 10px !important;
            right: 10px !important;
            width: 26px !important;
            height: 26px !important;
            border-radius: 50% !important;
            background: transparent !important;
            backdrop-filter: blur(4px) !important;
            -webkit-backdrop-filter: blur(4px) !important;
            color: #ffffff !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            border: 1px solid rgba(255, 255, 255, 0.4) !important;
            cursor: pointer !important;
            transition: all 0.2s ease !important;
            z-index: 20 !important;
            margin: 0 !important;
        }
        .gallery-trash-btn:hover { 
            transform: scale(1.1) !important; 
            background: #ff3b30 !important; 
            border-color: transparent !important;
            box-shadow: 0 4px 12px rgba(255, 59, 48, 0.3) !important;
        }
        
        /* 使用按钮：全透明边框风格 */
        .gallery-use-btn {
            position: absolute !important;
            top: 50% !important;
            left: 50% !important;
            transform: translate(-50%, -50%) !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding: 6px 16px !important;
            border-radius: 16px !important;
            background: transparent !important;
            color: #ffffff !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            border: 1px solid rgba(255, 255, 255, 0.7) !important;
            cursor: pointer !important;
            transition: all 0.2s ease !important;
            backdrop-filter: blur(4px) !important;
            -webkit-backdrop-filter: blur(4px) !important;
            z-index: 10 !important;
            margin: 0 !important;
            white-space: nowrap !important;
            text-shadow: 0 1px 4px rgba(0,0,0,0.4) !important;
        }
        .gallery-use-btn:hover { 
            transform: translate(-50%, -50%) scale(1.05) !important; 
            background: var(--accent, #007aff) !important;
            border-color: transparent !important;
            box-shadow: 0 4px 15px rgba(0, 122, 255, 0.3) !important;
        }

        .gallery-item-name {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 6px 8px;
            background: linear-gradient(transparent, rgba(0,0,0,0.8));
            color: white;
            font-size: 10px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            pointer-events: none;
        }
        .empty-gallery {
            grid-column: 1 / -1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 100px 20px;
            color: var(--ink-tertiary);
            text-align: center;
        }
        .empty-gallery svg {
            width: 48px;
            height: 48px;
            margin-bottom: 16px;
            opacity: 0.2;
        }
    `;
    document.head.appendChild(style);

    // 2. 注入 Modal HTML
    const modalHtml = `
        <div id="galleryModal" class="lightbox">
            <div class="history-modal-content">
                <div class="history-modal-header" style="padding: 16px 20px; border-bottom: 1px solid var(--border); position: relative;">
                    <h3 style="margin: 0; font-size: 18px; font-weight: 700; display: inline-flex; align-items: center; gap: 10px;">
                        我的上传图库
                        <button id="clearAllUploadsBtn" class="btn" title="清空图库"
                            style="width: 24px; height: 24px; padding: 0; border-radius: 6px; background: transparent; border: 1px solid rgba(255, 59, 48, 0.3); color: #ff3b30; cursor: pointer; transition: all 0.2s; display: none; align-items: center; justify-content: center; position: static !important;">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px;">
                                <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6" />
                            </svg>
                        </button>
                    </h3>
                    
                    <button id="closeGalleryModal" class="btn icon-btn" type="button" title="关闭"
                        style="border:none;background:transparent;width:32px;height:32px;color:var(--ink-secondary); position: absolute !important; right: 12px; top: 14px;">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 6 6 18" />
                            <path d="m6 6 12 12" />
                        </svg>
                    </button>
                </div>
                <div class="gallery-modal-body">
                    <div id="galleryList" class="gallery-grid">
                        <div class="empty-gallery">正在加载...</div>
                    </div>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // 3. 业务逻辑
    const modal = document.getElementById('galleryModal');
    const closeBtn = document.getElementById('closeGalleryModal');
    const listContainer = document.getElementById('galleryList');
    const clearAllBtn = document.getElementById('clearAllUploadsBtn');
    let galleryModeIsPublic = false; // 当前图库打开的模式

    window.openUploadGalleryModal = async function (isPublic = false) {
        galleryModeIsPublic = isPublic;

        // 动态更新标题文字 (保留图标按钮)
        const titleText = isPublic ? "我的图库(公共R2)" : "我的图库(私有R2)";
        const h3 = document.querySelector('#galleryModal h3');
        if (h3) {
            // 只替换第一个文本节点
            if (h3.childNodes[0].nodeType === 3) {
                h3.childNodes[0].textContent = titleText;
            }
        }

        modal.classList.add('show');
        await fetchUploads();
    };

    closeBtn.onclick = () => modal.classList.remove('show');
    modal.onclick = (e) => { if (e.target === modal) modal.classList.remove('show'); };

    async function fetchUploads() {
        try {
            listContainer.innerHTML = '<div class="empty-gallery">正在同步云端记录...</div>';
            const resp = await fetch(`/api/uploads?session_id=${SESSION_ID}&is_public=${galleryModeIsPublic}`);
            const data = await resp.json();

            const hasItems = data.uploads && data.uploads.length > 0;

            if (hasItems) {
                clearAllBtn.style.display = 'inline-flex';
            } else {
                clearAllBtn.style.display = 'none';
            }

            if (!hasItems) {
                listContainer.innerHTML = `
                    <div class="empty-gallery">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                            <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242M12 12v9m-4-4 4 4 4-4" />
                        </svg>
                        <p>暂无历史上传记录</p>
                    </div>`;
                return;
            }

            listContainer.innerHTML = data.uploads.reverse().map(item => `
                <div class="gallery-item">
                    <img src="${item.url}" loading="lazy" />
                    <div class="gallery-item-name">${item.name || '未命名图片'}</div>
                    <div class="gallery-item-actions">
                        <button class="gallery-trash-btn" onclick="deleteRemoteUpload('${item.url}')" title="永久删除">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6" />
                            </svg>
                        </button>
                        <button class="gallery-use-btn" onclick="useRemoteUpload('${item.url}', '${item.name}')">使用图片</button>
                    </div>
                </div>
            `).join('');
        } catch (err) {
            listContainer.innerHTML = `<div class="empty-gallery">加载失败: ${err.message}</div>`;
        }
    }

    clearAllBtn.onclick = async function () {
        if (!confirm('确定要清空所有上传记录吗？这会物理删除所有相关云端图片！')) return;

        try {
            const form = new FormData();
            form.append("session_id", SESSION_ID);
            form.append("is_public", galleryModeIsPublic);

            // 如果是私有模式，带上 R2 配置
            if (!galleryModeIsPublic) {
                const r2 = getR2Config();
                if (r2) Object.entries(r2).forEach(([k, v]) => form.append(k, v));
            }

            clearAllBtn.disabled = true;
            clearAllBtn.textContent = '删除中...';

            const resp = await fetch(`/api/delete-all-uploads`, {
                method: 'POST',
                body: form
            });
            const data = await resp.json();
            if (data.success) {
                logSystem(`图库已清空 (${data.count} 张图片)`);
                fetchUploads();
            }
        } catch (err) {
            alert("操作失败: " + err.message);
        } finally {
            clearAllBtn.disabled = false;
            clearAllBtn.style.opacity = '1';
        }
    };

    window.deleteRemoteUpload = async function (url) {
        if (!confirm('确定要物理删除这张图片吗？')) return;

        try {
            const respList = await fetch(`/api/uploads?session_id=${SESSION_ID}`);
            const dataList = await respList.json();
            const target = dataList.uploads.find(u => u.url === url);

            const form = new FormData();
            form.append("url", url);
            form.append("session_id", SESSION_ID);

            if (target && !target.is_public) {
                const r2 = getR2Config();
                if (r2) Object.entries(r2).forEach(([k, v]) => form.append(k, v));
            }

            const resp = await fetch(`/api/delete-upload`, {
                method: 'POST',
                body: form
            });
            const data = await resp.json();
            if (data.success) {
                logSystem(data.physical_delete ? "已从云端删除" : "记录已移除");
                fetchUploads();
            }
        } catch (err) {
            alert("操作失败: " + err.message);
        }
    };

    window.useRemoteUpload = function (url, name) {
        if (uploadedImages.some(img => img.url === url)) {
            logSystem("图片已在列表中");
            modal.classList.remove('show');
            return;
        }

        const entry = {
            url: url,
            name: name || "云端引用",
            preview: url,
            hash: "remote_" + Math.random().toString(36).substr(2, 9),
            cached: true,
            provider: "r2",
            dimensions: ""
        };

        uploadedImages.push(entry);
        renderThumbs();
        getImageDimensions(url).then(dims => {
            entry.dimensions = dims;
            renderThumbs();
        });

        logSystem("已引用云端图片");
        modal.classList.remove('show');
    };

    // 4. 环境感知：隐藏未配置的公共存储入口
    const updateGalleryUIByEnvironment = () => {
        const config = window.SERVER_CONFIG || {};
        const isPublicMode = getUploadProvider() === "public";
        const hintEl = document.getElementById('uploadProviderHint');
        const publicTab = document.getElementById('uploadProviderPublic')?.parentElement;

        // 不再隐藏公共存储，由用户自行决定
        // 但如果未配置，依然需要给出状态切换逻辑 (可选)
        if (!config.has_public_r2) {
            if (isPublicMode && els.uploadProviderR2) {
                // 不强制切换，除非当前完全不可用
            }
        }

        // 统一更新提示语逻辑
        if (hintEl) {
            const currentProvider = getUploadProvider();
            const isR2 = currentProvider === "r2";

            // 如果是公共模式但服务器没配置，显示错误提示
            if (!isR2 && !config.has_public_r2) {
                hintEl.innerHTML = `<span style="color:var(--error);">服务器未配置公共 R2 存储。</span> <span class="btn-manage-link" onclick="openUploadGalleryModal(true)">[管理公共存储]</span>`;
            } else {
                const text = isR2 ? "图片将上传至你在设置中配置的私有 R2 存储。" : "图片将独立存储在管理员配置的公共 R2 存储中。";
                const modeParam = isR2 ? "false" : "true";
                hintEl.innerHTML = `${text} <span class="btn-manage-link" onclick="openUploadGalleryModal(${modeParam})">[管理上传图片]</span>`;
            }
        }
    };

    // 覆盖 index.html 的原始函数
    window.updateUploadProviderHint = updateGalleryUIByEnvironment;

    // 初始化触发一次
    setTimeout(updateGalleryUIByEnvironment, 100);
})();
