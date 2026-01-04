/**
 * Admin Dashboard Vue.js Application
 * Features: Upload handling, storage monitoring, system control, and API interactions
 */

const { createApp } = Vue;

createApp({
    data() {
        return {
            // UI State
            sidebarCollapsed: window.innerWidth <= 992,
            currentView: 'dashboard',
            isDarkMode: localStorage.getItem('darkMode') === 'true',
            isLoading: false,
            connectionStatus: 'connected',
            userAvatar: 'https://ui-avatars.com/api/?name=Admin&background=0D8ABC&color=fff',
            
            viewTitles: {
                dashboard: 'System Dashboard',
                uploads: 'File Uploads',
                storage: 'Storage & Mounts',
                system: 'System Control',
                media: 'Media Library',
                settings: 'Settings',
                logs: 'System Logs'
            },

            // Authentication
            isAuthenticated: false,
            currentUser: null,
            apiToken: localStorage.getItem('adminToken') || null,

            // Logs State
            logLines: 100,
            logs: [],

            // System Stats
            stats: {
                storageUsed: 0,
                storageTotal: 0,
                storagePercent: 0,
                cpuPercent: 0,
                cpuCores: 0,
                cpuFreq: 0,
                throttled: false,
                ramUsed: 0,
                ramTotal: 0,
                ramPercent: 0,
                networkUp: 0,
                networkDown: 0,
                temperature: 0,
                uptime: 0
            },

            // Media Stats
            mediaStats: {
                movies: 0,
                shows: 0,
                music: 0,
                books: 0
            },

            // Uploads
            uploads: [],
            showUploadModal: false,
            maxFileSize: 5 * 1024 * 1024 * 1024, // 5GB
            allowedFileTypes: ['video/*', 'image/*', 'application/pdf', 'text/*', 'audio/*'],

            // Storage & Drives
            drives: [],
            
            // System Control
            services: [],
            
            // Update State
            updateStatus: {
                available: false,
                updating: false,
                progress: 0,
                message: '',
                error: null
            },

            // Confirmation Modal
            showConfirmModal: false,
            confirmModal: {
                title: '',
                message: '',
                action: null,
                actionText: 'Confirm',
                actionClass: 'btn-primary'
            },

            // Settings
            settings: {
                autoRefresh: true,
                refreshInterval: 5000,
                maxRetries: 3,
                notifications: true,
                omdb_key: ''
            },

            // Password Change
            passChange: {
                current: '',
                new: '',
                confirm: '',
                loading: false
            },

            // Toasts
            toasts: [],

            // Charts
            storageChart: null,
            resourcesChart: null
        };
    },

    computed: {
        activeUploadsCount() {
            return this.uploads.filter(u => u.status === 'uploading').length;
        }
    },

    methods: {
        async init() {
            console.log('Initializing Admin Dashboard (Vue 3)...');
            await this.checkAuthentication();
            
            if (this.isAuthenticated) {
                await Promise.all([
                    this.loadSystemStats(),
                    this.loadStorageInfo(),
                    this.loadMediaStats(),
                    this.loadServices(),
                    this.loadSettings(),
                    this.checkUpdates()
                ]);
                
                this.initCharts();
                this.startAutoRefresh();
            }

            // Apply theme
            if (this.isDarkMode) {
                document.body.classList.add('dark-mode');
            }
        },

        async checkAuthentication() {
            try {
                // If no token, we should probably redirect, but let's try the API first
                const response = await this.apiCall('/api/auth/me', 'GET');
                this.isAuthenticated = true;
                this.currentUser = response.user;
                this.connectionStatus = 'connected';
            } catch (error) {
                console.warn('Authentication check failed:', error);
                this.isAuthenticated = false;
                this.connectionStatus = 'disconnected';
                this.redirectToLogin();
            }
        },

        async loadSystemStats() {
            try {
                const response = await this.apiCall('/api/system/stats', 'GET');
                this.stats.cpuPercent = response.cpu || 0;
                this.stats.cpuCores = response.cores || 0;
                this.stats.cpuFreq = response.cpu_freq || 0;
                this.stats.throttled = response.throttled || false;
                this.stats.ramUsed = response.memory_used || 0;
                this.stats.ramTotal = response.memory_total || 0;
                this.stats.ramPercent = response.memory_percent || 0;
                this.stats.networkUp = response.network_up || 0;
                this.stats.networkDown = response.network_down || 0;
                this.stats.temperature = response.temp || 0;
                this.stats.uptime = response.uptime || 0;
                
                this.updateResourcesChart();
            } catch (error) {
                console.error('Error loading system stats:', error);
            }
        },

        async loadStorageInfo() {
            try {
                const response = await this.apiCall('/api/system/storage/info', 'GET');
                this.stats.storageUsed = response.used || 0;
                this.stats.storageTotal = response.total || 0;
                this.stats.storagePercent = response.percentage || 0;
                this.drives = response.disks || [];
                
                this.updateStorageChart();
            } catch (error) {
                console.error('Error loading storage info:', error);
            }
        },

        async loadMediaStats() {
            try {
                const response = await this.apiCall('/api/media/stats', 'GET');
                this.mediaStats = response;
            } catch (error) {
                console.error('Error loading media stats:', error);
            }
        },

        async loadSettings() {
            try {
                const response = await this.apiCall('/api/system/settings/omdb', 'GET');
                this.settings.omdb_key = response.key;
            } catch (error) {
                console.error('Error loading settings:', error);
            }
        },

        async fetchLogs() {
            try {
                const response = await this.apiCall(`/api/system/logs?lines=${this.logLines}`, 'GET');
                this.logs = response.logs || "No logs available.";
                this.$nextTick(() => {
                    if (this.$refs.logViewer) {
                        this.$refs.logViewer.scrollTop = this.$refs.logViewer.scrollHeight;
                    }
                });
            } catch (error) {
                console.error('Error fetching logs:', error);
                this.showNotification('Failed to fetch logs', 'error');
            }
        },

        clearLogView() {
            this.logs = "Log view cleared (fetch again to refresh).";
        },

        async systemControl(action) {
            this.showConfirmModal = true;
            const titles = { reboot: 'Reboot System', shutdown: 'Shutdown System', update: 'Update System' };
            const messages = { 
                reboot: 'Are you sure you want to reboot the system? The server will be unavailable for a few minutes.',
                shutdown: 'Are you sure you want to shutdown the system? You will need to manually power it back on.',
                update: 'Are you sure you want to update from GitHub? This will pull the latest changes.'
            };
            
            this.confirmModal = {
                title: titles[action] || 'System Control',
                message: messages[action] || `Confirm ${action}?`,
                action: async () => {
                    try {
                        const response = await this.apiCall('/api/system/control', 'POST', { action });
                        this.showNotification(response.message || 'Action initiated', 'success');
                    } catch (error) {
                        this.showNotification(`Action failed: ${error.message}`, 'error');
                    }
                },
                actionText: action.charAt(0).toUpperCase() + action.slice(1),
                actionClass: action === 'shutdown' || action === 'reboot' ? 'btn-danger' : 'btn-primary'
            };
        },

        async loadServices() {
            try {
                const response = await this.apiCall('/api/system/services', 'GET');
                this.services = response.services || [];
            } catch (error) {
                console.error('Error loading services:', error);
            }
        },

        async checkUpdates() {
            try {
                const response = await this.apiCall('/api/system/update/check', 'GET');
                this.updateStatus.available = response.available;
            } catch (error) {
                console.error('Update check error:', error);
            }
        },

        async performUpdate() {
            this.showConfirmModal = true;
            this.confirmModal = {
                title: 'System Update',
                message: 'Are you sure you want to update? The system will pull latest changes and restart. This will disconnect all active sessions.',
                action: async () => {
                    this.showConfirmModal = false;
                    try {
                        this.updateStatus.updating = true;
                        this.updateStatus.progress = 5;
                        this.updateStatus.message = 'Starting update...';
                        
                        await this.apiCall('/api/system/control/update', 'POST');
                        this.pollUpdateStatus();
                    } catch (error) {
                        this.updateStatus.updating = false;
                        this.showNotification('Failed to start update', 'error');
                    }
                },
                actionText: 'Update Now',
                actionClass: 'btn-success'
            };
        },

        async pollUpdateStatus() {
            if (!this.updateStatus.updating) return;

            try {
                const response = await this.apiCall('/api/system/update/status', 'GET');
                this.updateStatus.progress = response.progress;
                this.updateStatus.message = response.message;

                if (response.progress >= 90) {
                    this.updateStatus.message = 'Update complete! System is restarting...';
                    this.handleSystemRestart();
                    return;
                }
                setTimeout(() => this.pollUpdateStatus(), 2000);
            } catch (error) {
                if (this.updateStatus.progress >= 80) {
                    this.handleSystemRestart();
                } else {
                    setTimeout(() => this.pollUpdateStatus(), 5000);
                }
            }
        },

        async handleSystemRestart() {
            this.updateStatus.message = 'System is restarting. Reconnecting...';
            this.isLoading = true;
            this.connectionStatus = 'disconnected';

            const checkOnline = async () => {
                try {
                    const response = await fetch('/api/auth/me', {
                        credentials: 'same-origin'
                    });
                    if (response.ok) {
                        this.updateStatus.updating = false;
                        this.isLoading = false;
                        this.connectionStatus = 'connected';
                        this.showNotification('System is back online!', 'success');
                        setTimeout(() => window.location.reload(), 1000);
                    } else {
                        setTimeout(checkOnline, 3000);
                    }
                } catch (error) {
                    setTimeout(checkOnline, 3000);
                }
            };
            setTimeout(checkOnline, 5000);
        },

        async rebuildLibrary() {
            try {
                this.isLoading = true;
                await this.apiCall('/api/media/rebuild', 'POST');
                this.showNotification('Library rebuild initiated', 'success');
                await this.loadMediaStats();
            } catch (error) {
                this.showNotification('Failed to rebuild library', 'error');
            } finally {
                this.isLoading = false;
            }
        },

        async changePassword() {
            if (this.passChange.new !== this.passChange.confirm) {
                this.showNotification('New passwords do not match', 'error');
                return;
            }

            try {
                this.passChange.loading = true;
                await this.apiCall('/api/auth/change-password', 'POST', {
                    current_password: this.passChange.current,
                    new_password: this.passChange.new
                });
                this.showNotification('Password changed successfully', 'success');
                this.passChange = { current: '', new: '', confirm: '', loading: false };
            } catch (error) {
                this.showNotification(error.response?.data?.detail || 'Failed to change password', 'error');
            } finally {
                this.passChange.loading = false;
            }
        },

        async saveOmdbKey() {
            try {
                await this.apiCall('/api/system/settings/omdb', 'POST', {
                    key: this.settings.omdb_key
                });
                this.showNotification('OMDb key saved successfully', 'success');
            } catch (error) {
                this.showNotification('Failed to save OMDb key', 'error');
            }
        },

        async confirmReboot() {
            this.showConfirmModal = true;
            this.confirmModal = {
                title: 'System Reboot',
                message: 'Are you sure you want to reboot the Nomad Pi?',
                action: async () => {
                    this.showConfirmModal = false;
                    try {
                        await this.apiCall('/api/system/control/reboot', 'POST');
                        this.handleSystemRestart();
                    } catch (error) {
                        this.showNotification('Failed to initiate reboot', 'error');
                    }
                },
                actionText: 'Reboot',
                actionClass: 'btn-warning'
            };
        },

        async confirmShutdown() {
            this.showConfirmModal = true;
            this.confirmModal = {
                title: 'System Shutdown',
                message: 'Are you sure you want to shut down the Nomad Pi?',
                action: async () => {
                    this.showConfirmModal = false;
                    try {
                        await this.apiCall('/api/system/control/shutdown', 'POST');
                        this.showNotification('System is shutting down...', 'warning');
                    } catch (error) {
                        this.showNotification('Failed to initiate shutdown', 'error');
                    }
                },
                actionText: 'Shutdown',
                actionClass: 'btn-danger'
            };
        },

        async scanDrives() {
            try {
                this.isLoading = true;
                await this.apiCall('/api/system/storage/scan', 'POST');
                await this.loadStorageInfo();
                this.showNotification('Drive scan complete', 'success');
            } catch (error) {
                this.showNotification('Failed to scan drives', 'error');
            } finally {
                this.isLoading = false;
            }
        },

        async mountDrive(drive) {
            try {
                this.isLoading = true;
                await this.apiCall('/api/system/mount', 'POST', {
                    device: drive.device,
                    mount_point: drive.label || drive.device.split('/').pop()
                });
                this.showNotification(`Drive ${drive.device} mounted successfully`, 'success');
                await this.loadStorageInfo();
            } catch (error) {
                this.showNotification(`Failed to mount ${drive.device}`, 'error');
            } finally {
                this.isLoading = false;
            }
        },

        async unmountDrive(drive) {
            try {
                this.isLoading = true;
                await this.apiCall('/api/system/unmount', 'POST', {
                    target: drive.mountpoint
                });
                this.showNotification(`Drive ${drive.device} unmounted successfully`, 'success');
                await this.loadStorageInfo();
            } catch (error) {
                this.showNotification(`Failed to unmount ${drive.device}`, 'error');
            } finally {
                this.isLoading = false;
            }
        },

        toggleSidebar() {
            this.sidebarCollapsed = !this.sidebarCollapsed;
        },

        setView(view) {
            this.currentView = view;
            if (window.innerWidth <= 992) {
                this.sidebarCollapsed = true;
            }
        },

        toggleTheme() {
            this.isDarkMode = !this.isDarkMode;
            localStorage.setItem('darkMode', this.isDarkMode);
            document.body.classList.toggle('dark-mode', this.isDarkMode);
        },

        formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        },

        getFileIcon(filename) {
            const ext = filename.split('.').pop().toLowerCase();
            const icons = {
                mp4: 'fas fa-file-video', mkv: 'fas fa-file-video', avi: 'fas fa-file-video',
                mp3: 'fas fa-file-audio', flac: 'fas fa-file-audio', wav: 'fas fa-file-audio',
                jpg: 'fas fa-file-image', jpeg: 'fas fa-file-image', png: 'fas fa-file-image',
                pdf: 'fas fa-file-pdf', txt: 'fas fa-file-alt', zip: 'fas fa-file-archive'
            };
            return icons[ext] || 'fas fa-file';
        },

        handleFileSelect(event) {
            const files = Array.from(event.target.files);
            this.addFilesToUpload(files);
        },

        handleDrop(event) {
            const files = Array.from(event.dataTransfer.files);
            this.addFilesToUpload(files);
        },

        addFilesToUpload(files) {
            files.forEach(file => {
                const upload = {
                    id: Date.now() + Math.random().toString(36).substr(2, 9),
                    name: file.name,
                    size: file.size,
                    progress: 0,
                    status: 'pending',
                    file: file
                };
                this.uploads.push(upload);
                this.startUpload(upload);
            });
        },

        async startUpload(upload) {
            upload.status = 'uploading';
            const formData = new FormData();
            formData.append('file', upload.file);
            
            try {
                const xhr = new XMLHttpRequest();
                xhr.withCredentials = true;

                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        upload.progress = Math.round((e.loaded / e.total) * 100);
                    }
                };
                
                xhr.onload = () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        upload.status = 'completed';
                        upload.progress = 100;
                        this.showNotification(`Uploaded ${upload.name}`, 'success');
                        this.loadStorageInfo();
                    } else {
                        upload.status = 'failed';
                        this.showNotification(`Upload failed: ${upload.name}`, 'error');
                    }
                };
                
                xhr.onerror = () => {
                    upload.status = 'failed';
                    this.showNotification(`Network error uploading ${upload.name}`, 'error');
                };
                
                xhr.open('POST', '/api/uploads/single', true);
                xhr.send(formData);
            } catch (error) {
                upload.status = 'failed';
            }
        },

        removeUpload(id) {
            this.uploads = this.uploads.filter(u => u.id !== id);
        },

        async apiCall(endpoint, method = 'GET', data = null) {
            const options = {
                method,
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin'
            };
            if (data) {
                options.body = JSON.stringify(data);
            }

            try {
                const response = await fetch(endpoint, options);
                if (!response.ok) {
                    if (response.status === 401) {
                        this.isAuthenticated = false;
                        this.redirectToLogin();
                    }
                    throw new Error(`API Error: ${response.status}`);
                }
                return await response.json();
            } catch (error) {
                console.error(`API Call failed: ${endpoint}`, error);
                throw error;
            }
        },

        showNotification(message, type = 'info') {
            const id = Date.now();
            this.toasts.push({ id, message, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 5000);
        },

        getToastIcon(type) {
            switch (type) {
                case 'success': return 'fas fa-check-circle';
                case 'error': return 'fas fa-exclamation-circle';
                case 'warning': return 'fas fa-exclamation-triangle';
                default: return 'fas fa-info-circle';
            }
        },

        redirectToLogin() {
            window.location.href = '/';
        },

        startAutoRefresh() {
            if (this.settings.autoRefresh) {
                setInterval(() => {
                    if (this.currentView === 'dashboard') {
                        this.loadSystemStats();
                        this.loadStorageInfo();
                    }
                    if (this.currentView === 'logs') {
                        this.fetchLogs();
                    }
                }, this.settings.refreshInterval);
            }
        },

        initCharts() {
            // Storage Chart
            const storageCtx = document.getElementById('storageChart')?.getContext('2d');
            if (storageCtx) {
                this.storageChart = new Chart(storageCtx, {
                    type: 'doughnut',
                    data: {
                        labels: ['Used', 'Free'],
                        datasets: [{
                            data: [this.stats.storageUsed, this.stats.storageTotal - this.stats.storageUsed],
                            backgroundColor: ['#3498db', '#ecf0f1']
                        }]
                    },
                    options: { responsive: true, maintainAspectRatio: false }
                });
            }

            // Resources Chart
            const resourcesCtx = document.getElementById('resourcesChart')?.getContext('2d');
            if (resourcesCtx) {
                this.resourcesChart = new Chart(resourcesCtx, {
                    type: 'line',
                    data: {
                        labels: Array(10).fill(''),
                        datasets: [
                            {
                                label: 'CPU %',
                                data: Array(10).fill(0),
                                borderColor: '#e74c3c',
                                tension: 0.4
                            },
                            {
                                label: 'RAM %',
                                data: Array(10).fill(0),
                                borderColor: '#2ecc71',
                                tension: 0.4
                            }
                        ]
                    },
                    options: { responsive: true, maintainAspectRatio: false }
                });
            }
        },

        updateStorageChart() {
            if (this.storageChart) {
                this.storageChart.data.datasets[0].data = [
                    this.stats.storageUsed,
                    Math.max(0, this.stats.storageTotal - this.stats.storageUsed)
                ];
                this.storageChart.update();
            }
        },

        updateResourcesChart() {
            if (this.resourcesChart) {
                const cpuData = this.resourcesChart.data.datasets[0].data;
                const ramData = this.resourcesChart.data.datasets[1].data;
                
                cpuData.push(this.stats.cpuPercent);
                cpuData.shift();
                
                ramData.push(this.stats.ramPercent);
                ramData.shift();
                
                this.resourcesChart.update();
            }
        }
    },

    mounted() {
        this.init();
    }
}).mount('#app');
