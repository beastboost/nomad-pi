/* Nomad Pi media management actions.
 * Restores Rename/Delete controls for movie detail pages and whole-show pages
 * without coupling those controls back into the legacy renderers.
 */
(() => {
    if (typeof api !== 'function' || typeof openSheet !== 'function') return;

    function parentPath(path) {
        const parts = String(path || '').split('/').filter(Boolean);
        if (parts.length <= 1) return '/';
        parts.pop();
        return '/' + parts.join('/');
    }

    function episodePaths(show) {
        const paths = [];
        for (const season of (show?.seasons || [])) {
            for (const episode of (season?.episodes || [])) {
                if (episode?.path) paths.push(String(episode.path));
            }
        }
        return paths;
    }

    function commonDirectory(paths) {
        const dirs = paths.map(path => parentPath(path));
        if (!dirs.length) return null;
        const split = dirs.map(path => path.split('/').filter(Boolean));
        let common = split[0].slice();
        for (const parts of split.slice(1)) {
            let i = 0;
            while (i < common.length && i < parts.length && common[i] === parts[i]) i++;
            common = common.slice(0, i);
            if (!common.length) return null;
        }
        return '/' + common.join('/');
    }

    function inferShowRoot(show) {
        let root = commonDirectory(episodePaths(show));
        if (!root) return null;

        // A one-season show commonly yields .../Show Name/Season 1 as the
        // common directory. Whole-show operations belong one level above.
        const tail = baseName(root);
        if (/^(?:season|series)\s*\d+$/i.test(tail) || /^s\d{1,3}$/i.test(tail)) {
            root = parentPath(root);
        }
        return root;
    }

    function refreshLibraryAfterManage() {
        closeSheet();
        if (S?.screen === 'detail' || S?.screen === 'sub') {
            if (typeof back === 'function') back();
        }
        if (typeof loadLibrary === 'function') loadLibrary();
    }

    function openManageMenu(path, { directory = false, title = null } = {}) {
        if (!path) {
            toast('Could not determine the media path.', 'error', 4500);
            return;
        }
        const label = title || baseName(path);
        openSheet(`
          <div class="kicker" style="margin-bottom:4px">${directory ? 'Show' : 'Movie'}</div>
          <div style="font-size:15px;margin-bottom:14px;word-break:break-word">${escapeHtml(label)}</div>
          <div class="list">
            <button class="sheet-option row-rule" id="media-manage-rename">
              <span>Rename</span><i class="ph ph-pencil-simple"></i>
            </button>
            ${directory ? '' : `
              <button class="sheet-option row-rule" id="media-manage-download">
                <span>Download</span><i class="ph ph-download-simple"></i>
              </button>`}
            <button class="sheet-option row-rule" id="media-manage-delete" style="color:#e0a1a1">
              <span>Delete</span><i class="ph ph-trash"></i>
            </button>
          </div>`);

        $('#media-manage-rename')?.addEventListener('click', () => openManageRename(path, { directory, title: label }));
        $('#media-manage-download')?.addEventListener('click', () => {
            closeSheet();
            if (typeof downloadFile === 'function') downloadFile(path);
        });
        $('#media-manage-delete')?.addEventListener('click', () => deleteManagedMedia(path, { directory, title: label }));
    }

    function openManageRename(path, { directory = false, title = null } = {}) {
        const name = baseName(path);
        const suffix = directory ? '' : (ext(name) ? `.${ext(name)}` : '');
        const editable = directory ? name : stripExt(name);

        openSheet(`
          <div class="kicker" style="margin-bottom:12px">Rename ${directory ? 'show' : 'movie'}</div>
          <input class="input input-plain" id="media-rn-name" value="${escapeHtml(editable)}" autocomplete="off">
          <div style="font-size:12px;color:var(--text-45);margin-top:6px">${suffix ? `${escapeHtml(suffix)} is kept` : ''}</div>
          <div id="media-rn-status" style="font-size:12.5px;color:var(--text-45);min-height:18px;margin-top:8px"></div>
          <button class="btn btn-primary btn-block" id="media-rn-save" style="min-height:48px;margin-top:6px">Rename</button>`);

        $('#media-rn-save')?.addEventListener('click', async () => {
            const next = $('#media-rn-name')?.value.trim();
            const status = $('#media-rn-status');
            if (!next) {
                if (status) status.textContent = 'Enter a name.';
                return;
            }
            if (/[\\/\x00]/.test(next)) {
                if (status) status.textContent = 'The name cannot contain / or \\.';
                return;
            }
            const newPath = `${parentPath(path)}/${next}${suffix}`;
            if (newPath === path) {
                closeSheet();
                return;
            }
            if (status) status.textContent = 'Renaming…';
            try {
                await api('/media/rename', {
                    method: 'POST',
                    body: JSON.stringify({ old_path: path, new_path: newPath }),
                });
                toast(`${directory ? 'Show' : 'Movie'} renamed`, 'success', 3000);
                refreshLibraryAfterManage();
            } catch (err) {
                if (status) status.textContent = err?.message || 'Could not rename.';
            }
        });
    }

    async function deleteManagedMedia(path, { directory = false, title = null } = {}) {
        const label = title || baseName(path);
        const message = directory
            ? `${label} and every episode inside its show folder will be permanently removed from the Pi. This cannot be undone.`
            : `${label} will be permanently removed from the Pi. This cannot be undone.`;
        const ok = await confirmDialog(
            directory ? 'Delete this entire show?' : 'Delete this movie?',
            message,
            'Delete'
        );
        if (!ok) return;

        try {
            await api(`/media/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
            toast(directory ? 'Show deleted' : 'Movie deleted', 'success', 3000);
            refreshLibraryAfterManage();
        } catch (err) {
            toast(err?.message || `Could not delete that ${directory ? 'show' : 'movie'}`, 'error', 6500);
        }
    }

    // Movie details: append a manage button beside Play/Watchlist/Watched.
    if (typeof openDetail === 'function') {
        const previousOpenDetail = openDetail;
        openDetail = async function nomadManagedOpenDetail(path, ...args) {
            const result = await previousOpenDetail(path, ...args);
            if (kindOf(path) === 'video') {
                const actions = $('#detail-body .detail-actions');
                if (actions && !actions.querySelector('[data-media-manage-movie]')) {
                    const button = document.createElement('button');
                    button.className = 'btn btn-icon';
                    button.dataset.mediaManageMovie = path;
                    button.setAttribute('aria-label', 'Manage movie');
                    button.innerHTML = '<i class="ph ph-dots-three-vertical"></i>';
                    actions.appendChild(button);
                }
            }
            return result;
        };
    }

    // Show pages already use the generic sub-page header, including a reserved
    // action button. Reuse it instead of adding another floating control.
    if (typeof openShow === 'function') {
        const previousOpenShow = openShow;
        openShow = function nomadManagedOpenShow(index, ...args) {
            const show = (typeof SHOWS !== 'undefined' ? SHOWS.list?.[Number(index)] : null);
            const result = previousOpenShow(index, ...args);
            const root = inferShowRoot(show);
            const action = $('#sub-action');
            if (action && root) {
                action.classList.remove('hidden');
                action.innerHTML = '<i class="ph ph-dots-three-vertical"></i>';
                action.setAttribute('aria-label', 'Manage show');
                action.onclick = event => {
                    event.preventDefault();
                    openManageMenu(root, { directory: true, title: show?.name || baseName(root) });
                };
            }
            return result;
        };
    }

    document.addEventListener('click', event => {
        const movie = event.target.closest('[data-media-manage-movie]');
        if (!movie) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        openManageMenu(movie.dataset.mediaManageMovie, { directory: false });
    }, true);
})();
