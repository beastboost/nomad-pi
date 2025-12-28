/**
 * Admin Dashboard Vue.js Application
 * Features: Upload handling, storage monitoring, system control, and API interactions
 */

const AdminApp = new Vue({
  el: '#admin-app',
  data: {
    // Authentication
    isAuthenticated: false,
    currentUser: null,
    apiToken: localStorage.getItem('adminToken') || null,
    
    // UI State
    activeTab: 'dashboard',
    isLoading: false,
    notifications: [],
    darkMode: localStorage.getItem('darkMode') === 'true',
    
    // Dashboard Data
    systemStats: {
      cpuUsage: 0,
      memoryUsage: 0,
      diskUsage: 0,
      temperature: 0,
      uptime: 0,
      processes: 0,
    },
    
    // Storage Monitoring
    storageData: {
      total: 0,
      used: 0,
      available: 0,
      percentage: 0,
      breakdown: {
        videos: 0,
        images: 0,
        documents: 0,
        other: 0,
      },
      disks: [],
    },
    
    // File Upload
    uploadQueue: [],
    uploadProgress: {},
    maxFileSize: 5000000000, // 5GB
    allowedFileTypes: ['video/*', 'image/*', 'application/pdf', 'text/*', 'audio/*'],
    dragOver: false,
    
    // System Control
    services: [],
    systemInfo: {},
    logs: [],
    
    // API Configuration
    apiBaseUrl: '/api',
    apiEndpoints: {
      stats: '/api/system/stats',
      storage: '/api/storage/info',
      upload: '/api/files/upload',
      services: '/api/services',
      logs: '/api/logs',
      config: '/api/config',
    },
    
    // Pagination
    currentPage: 1,
    itemsPerPage: 20,
    totalItems: 0,
    
    // Search & Filter
    searchQuery: '',
    filterType: 'all',
    dateRange: {
      start: null,
      end: null,
    },
    
    // Modal States
    modals: {
      uploadModal: false,
      configModal: false,
      logViewerModal: false,
      serviceControlModal: false,
    },
    
    // Settings
    settings: {
      autoRefresh: true,
      refreshInterval: 5000,
      maxRetries: 3,
      timeout: 30000,
      notifications: true,
      logLevel: 'info',
    },
  },
  
  computed: {
    /**
     * Computed property for storage percentage
     */
    storagePercentage() {
      if (this.storageData.total === 0) return 0;
      return Math.round((this.storageData.used / this.storageData.total) * 100);
    },
    
    /**
     * Computed property for formatted storage
     */
    formattedStorage() {
      return {
        total: this.formatBytes(this.storageData.total),
        used: this.formatBytes(this.storageData.used),
        available: this.formatBytes(this.storageData.available),
      };
    },
    
    /**
     * Computed property for system health status
     */
    systemHealth() {
      const cpuHealth = this.systemStats.cpuUsage < 80 ? 'good' : 'warning';
      const memHealth = this.systemStats.memoryUsage < 85 ? 'good' : 'warning';
      const diskHealth = this.storagePercentage < 90 ? 'good' : 'warning';
      
      if (cpuHealth === 'warning' || memHealth === 'warning' || diskHealth === 'warning') {
        return 'warning';
      }
      return 'good';
    },
    
    /**
     * Active uploads count
     */
    activeUploadsCount() {
      return Object.values(this.uploadProgress).filter(p => p.status === 'uploading').length;
    },
    
    /**
     * Running services count
     */
    runningServicesCount() {
      return this.services.filter(s => s.status === 'running').length;
    },
    
    /**
     * Filtered logs based on search and date range
     */
    filteredLogs() {
      let filtered = this.logs;
      
      if (this.searchQuery) {
        const query = this.searchQuery.toLowerCase();
        filtered = filtered.filter(log =>
          log.message.toLowerCase().includes(query) ||
          log.source.toLowerCase().includes(query)
        );
      }
      
      if (this.filterType !== 'all') {
        filtered = filtered.filter(log => log.level === this.filterType);
      }
      
      if (this.dateRange.start && this.dateRange.end) {
        filtered = filtered.filter(log => {
          const logDate = new Date(log.timestamp);
          return logDate >= this.dateRange.start && logDate <= this.dateRange.end;
        });
      }
      
      return filtered;
    },
    
    /**
     * Paginated logs
     */
    paginatedLogs() {
      const start = (this.currentPage - 1) * this.itemsPerPage;
      const end = start + this.itemsPerPage;
      return this.filteredLogs.slice(start, end);
    },
  },
  
  methods: {
    /**
     * Initialize admin application
     */
    async init() {
      console.log('Initializing Admin Dashboard...');
      await this.checkAuthentication();
      
      if (this.isAuthenticated) {
        this.startAutoRefresh();
        await Promise.all([
          this.loadSystemStats(),
          this.loadStorageInfo(),
          this.loadServices(),
          this.loadLogs(),
        ]);
      }
    },
    
    /**
     * Check authentication status
     */
    async checkAuthentication() {
      try {
        const response = await this.apiCall('/api/auth/me', 'GET');
        this.isAuthenticated = true;
        this.currentUser = response.user;
      } catch (error) {
        console.warn('Authentication check failed:', error);
        this.isAuthenticated = false;
        this.redirectToLogin();
      }
    },
    
    /**
     * Load system statistics
     */
    async loadSystemStats() {
      try {
        this.isLoading = true;
        const response = await this.apiCall(this.apiEndpoints.stats, 'GET');
        
        this.systemStats = {
          cpuUsage: response.cpu || 0,
          memoryUsage: response.memory || 0,
          diskUsage: response.disk || 0,
          temperature: response.temperature || 0,
          uptime: response.uptime || 0,
          processes: response.processes || 0,
        };
      } catch (error) {
        this.showNotification('Failed to load system statistics', 'error');
        console.error('Error loading system stats:', error);
      } finally {
        this.isLoading = false;
      }
    },
    
    /**
     * Load storage information
     */
    async loadStorageInfo() {
      try {
        const response = await this.apiCall(this.apiEndpoints.storage, 'GET');
        
        this.storageData = {
          total: response.total || 0,
          used: response.used || 0,
          available: response.available || 0,
          percentage: response.percentage || 0,
          breakdown: response.breakdown || {
            videos: 0,
            images: 0,
            documents: 0,
            other: 0,
          },
          disks: response.disks || [],
        };
      } catch (error) {
        this.showNotification('Failed to load storage information', 'error');
        console.error('Error loading storage info:', error);
      }
    },
    
    /**
     * Load services status
     */
    async loadServices() {
      try {
        const response = await this.apiCall(this.apiEndpoints.services, 'GET');
        this.services = response.services || [];
      } catch (error) {
        this.showNotification('Failed to load services', 'error');
        console.error('Error loading services:', error);
      }
    },
    
    /**
     * Load system logs
     */
    async loadLogs(page = 1) {
      try {
        const response = await this.apiCall(
          `${this.apiEndpoints.logs}?page=${page}&limit=${this.itemsPerPage}`,
          'GET'
        );
        
        this.logs = response.logs || [];
        this.totalItems = response.total || 0;
        this.currentPage = page;
      } catch (error) {
        this.showNotification('Failed to load logs', 'error');
        console.error('Error loading logs:', error);
      }
    },
    
    /**
     * Handle file selection for upload
     */
    handleFileSelect(event) {
      const files = event.target.files || [];
      this.addFilesToQueue(Array.from(files));
    },
    
    /**
     * Handle drag and drop
     */
    handleDragOver(event) {
      event.preventDefault();
      this.dragOver = true;
    },
    
    handleDragLeave() {
      this.dragOver = false;
    },
    
    handleDrop(event) {
      event.preventDefault();
      this.dragOver = false;
      const files = event.dataTransfer.files || [];
      this.addFilesToQueue(Array.from(files));
    },
    
    /**
     * Add files to upload queue
     */
    addFilesToQueue(files) {
      files.forEach(file => {
        // Validate file
        if (!this.validateFile(file)) {
          return;
        }
        
        const fileId = `${file.name}-${Date.now()}`;
        this.uploadQueue.push({
          id: fileId,
          name: file.name,
          size: file.size,
          type: file.type,
          file: file,
          status: 'pending',
          createdAt: new Date(),
        });
        
        this.uploadProgress[fileId] = {
          status: 'pending',
          progress: 0,
          speed: 0,
          eta: 0,
        };
      });
      
      // Auto-start upload if enabled
      if (this.uploadQueue.length > 0) {
        this.processUploadQueue();
      }
    },
    
    /**
     * Validate file before upload
     */
    validateFile(file) {
      // Check file size
      if (file.size > this.maxFileSize) {
        this.showNotification(
          `File ${file.name} exceeds maximum size of ${this.formatBytes(this.maxFileSize)}`,
          'error'
        );
        return false;
      }
      
      // Check file type
      const isAllowed = this.allowedFileTypes.some(type => {
        if (type.endsWith('/*')) {
          return file.type.startsWith(type.replace('/*', ''));
        }
        return file.type === type;
      });
      
      if (!isAllowed) {
        this.showNotification(`File type ${file.type} is not allowed`, 'error');
        return false;
      }
      
      return true;
    },
    
    /**
     * Process upload queue
     */
    async processUploadQueue() {
      const pendingFile = this.uploadQueue.find(f => f.status === 'pending');
      
      if (!pendingFile) {
        return;
      }
      
      try {
        await this.uploadFile(pendingFile);
      } catch (error) {
        console.error('Upload error:', error);
        this.uploadProgress[pendingFile.id].status = 'failed';
        this.showNotification(`Upload failed for ${pendingFile.name}`, 'error');
      }
      
      // Process next file
      const nextPending = this.uploadQueue.find(f => f.status === 'pending');
      if (nextPending) {
        await this.processUploadQueue();
      }
    },
    
    /**
     * Upload a single file
     */
    async uploadFile(fileItem) {
      const formData = new FormData();
      formData.append('file', fileItem.file);
      formData.append('description', fileItem.name);
      
      this.uploadProgress[fileItem.id].status = 'uploading';
      fileItem.status = 'uploading';
      
      try {
        const xhr = new XMLHttpRequest();
        
        // Track upload progress
        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable) {
            const progress = Math.round((event.loaded / event.total) * 100);
            const speed = event.loaded / ((Date.now() - fileItem.createdAt.getTime()) / 1000);
            const eta = (event.total - event.loaded) / speed;
            
            this.uploadProgress[fileItem.id] = {
              status: 'uploading',
              progress,
              speed: this.formatBytes(speed) + '/s',
              eta: this.formatTime(eta),
            };
          }
        });
        
        // Handle completion
        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            this.uploadProgress[fileItem.id].status = 'completed';
            fileItem.status = 'completed';
            this.showNotification(`File ${fileItem.name} uploaded successfully`, 'success');
            this.loadStorageInfo(); // Refresh storage info
          } else {
            throw new Error(`Upload failed with status ${xhr.status}`);
          }
        });
        
        xhr.addEventListener('error', () => {
          this.uploadProgress[fileItem.id].status = 'failed';
          fileItem.status = 'failed';
          throw new Error('Network error during upload');
        });
        
        xhr.open('POST', this.apiEndpoints.upload, true);
        xhr.setRequestHeader('Authorization', `Bearer ${this.apiToken}`);
        xhr.send(formData);
        
        return new Promise((resolve, reject) => {
          xhr.addEventListener('loadend', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve();
            } else {
              reject(new Error(`Upload failed: ${xhr.statusText}`));
            }
          });
        });
      } catch (error) {
        this.uploadProgress[fileItem.id].status = 'failed';
        fileItem.status = 'failed';
        throw error;
      }
    },
    
    /**
     * Remove file from upload queue
     */
    removeFromQueue(fileId) {
      const index = this.uploadQueue.findIndex(f => f.id === fileId);
      if (index > -1) {
        this.uploadQueue.splice(index, 1);
        delete this.uploadProgress[fileId];
      }
    },
    
    /**
     * Control service (start, stop, restart)
     */
    async controlService(serviceName, action) {
      try {
        this.isLoading = true;
        const response = await this.apiCall(
          `${this.apiEndpoints.services}/${serviceName}/${action}`,
          'POST'
        );
        
        this.showNotification(
          `Service ${serviceName} ${action}ed successfully`,
          'success'
        );
        
        await this.loadServices();
      } catch (error) {
        this.showNotification(`Failed to ${action} service ${serviceName}`, 'error');
        console.error('Service control error:', error);
      } finally {
        this.isLoading = false;
      }
    },
    
    /**
     * Restart system
     */
    async restartSystem() {
      if (!confirm('Are you sure you want to restart the system? This will disconnect all users.')) {
        return;
      }
      
      try {
        this.isLoading = true;
        await this.apiCall('/api/system/restart', 'POST');
        this.showNotification('System restart initiated', 'info');
      } catch (error) {
        this.showNotification('Failed to restart system', 'error');
        console.error('System restart error:', error);
      } finally {
        this.isLoading = false;
      }
    },
    
    /**
     * Shutdown system
     */
    async shutdownSystem() {
      if (!confirm('Are you sure you want to shutdown the system?')) {
        return;
      }
      
      try {
        this.isLoading = true;
        await this.apiCall('/api/system/shutdown', 'POST');
        this.showNotification('System shutdown initiated', 'info');
      } catch (error) {
        this.showNotification('Failed to shutdown system', 'error');
        console.error('System shutdown error:', error);
      } finally {
        this.isLoading = false;
      }
    },
    
    /**
     * Update system settings
     */
    async updateSettings(newSettings) {
      try {
        this.isLoading = true;
        await this.apiCall(this.apiEndpoints.config, 'PUT', newSettings);
        
        Object.assign(this.settings, newSettings);
        localStorage.setItem('adminSettings', JSON.stringify(this.settings));
        
        this.showNotification('Settings updated successfully', 'success');
      } catch (error) {
        this.showNotification('Failed to update settings', 'error');
        console.error('Settings update error:', error);
      } finally {
        this.isLoading = false;
      }
    },
    
    /**
     * Clear logs
     */
    async clearLogs() {
      if (!confirm('Are you sure you want to clear all logs? This action cannot be undone.')) {
        return;
      }
      
      try {
        await this.apiCall(`${this.apiEndpoints.logs}`, 'DELETE');
        this.logs = [];
        this.showNotification('Logs cleared successfully', 'success');
      } catch (error) {
        this.showNotification('Failed to clear logs', 'error');
        console.error('Clear logs error:', error);
      }
    },
    
    /**
     * Export logs
     */
    exportLogs() {
      try {
        const dataStr = JSON.stringify(this.filteredLogs, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `logs-${new Date().toISOString().split('T')[0]}.json`;
        link.click();
        URL.revokeObjectURL(url);
        
        this.showNotification('Logs exported successfully', 'success');
      } catch (error) {
        this.showNotification('Failed to export logs', 'error');
        console.error('Export logs error:', error);
      }
    },
    
    /**
     * Generic API call function
     */
    async apiCall(endpoint, method = 'GET', data = null, retries = 0) {
      try {
        const options = {
          method,
          headers: {
            'Content-Type': 'application/json',
          },
        };
        
        if (this.apiToken) {
          options.headers['Authorization'] = `Bearer ${this.apiToken}`;
        }
        
        if (data) {
          options.body = JSON.stringify(data);
        }
        
        const response = await fetch(endpoint, options);
        
        if (!response.ok) {
          if (response.status === 401) {
            this.isAuthenticated = false;
            this.redirectToLogin();
          }
          throw new Error(`API error: ${response.status} ${response.statusText}`);
        }
        
        return await response.json();
      } catch (error) {
        if (retries < this.settings.maxRetries) {
          await this.sleep(1000);
          return this.apiCall(endpoint, method, data, retries + 1);
        }
        throw error;
      }
    },
    
    /**
     * Format bytes to human readable
     */
    formatBytes(bytes) {
      if (bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
    },
    
    /**
     * Format time in seconds to readable format
     */
    formatTime(seconds) {
      if (seconds < 60) return Math.round(seconds) + 's';
      if (seconds < 3600) return Math.round(seconds / 60) + 'm';
      return Math.round(seconds / 3600) + 'h';
    },
    
    /**
     * Format uptime
     */
    formatUptime(seconds) {
      const days = Math.floor(seconds / 86400);
      const hours = Math.floor((seconds % 86400) / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      
      let result = '';
      if (days > 0) result += `${days}d `;
      if (hours > 0) result += `${hours}h `;
      if (minutes > 0) result += `${minutes}m`;
      
      return result.trim() || '< 1m';
    },
    
    /**
     * Show notification
     */
    showNotification(message, type = 'info') {
      if (!this.settings.notifications) return;
      
      const notification = {
        id: Date.now(),
        message,
        type,
        timestamp: new Date(),
      };
      
      this.notifications.push(notification);
      
      // Auto-remove after 5 seconds
      setTimeout(() => {
        const index = this.notifications.findIndex(n => n.id === notification.id);
        if (index > -1) {
          this.notifications.splice(index, 1);
        }
      }, 5000);
    },
    
    /**
     * Toggle dark mode
     */
    toggleDarkMode() {
      this.darkMode = !this.darkMode;
      localStorage.setItem('darkMode', this.darkMode);
      document.body.classList.toggle('dark-mode', this.darkMode);
    },
    
    /**
     * Start auto-refresh of system stats
     */
    startAutoRefresh() {
      if (this.settings.autoRefresh) {
        setInterval(() => {
          this.loadSystemStats();
          this.loadStorageInfo();
        }, this.settings.refreshInterval);
      }
    },
    
    /**
     * Redirect to login page
     */
    redirectToLogin() {
      window.location.href = '/login';
    },
    
    /**
     * Sleep utility function
     */
    sleep(ms) {
      return new Promise(resolve => setTimeout(resolve, ms));
    },
  },
  
  watch: {
    /**
     * Watch for dark mode changes
     */
    darkMode(newVal) {
      document.body.classList.toggle('dark-mode', newVal);
    },
  },
  
  mounted() {
    console.log('Admin Dashboard mounted');
    this.init();
    
    // Apply dark mode on mount
    if (this.darkMode) {
      document.body.classList.add('dark-mode');
    }
  },
  
  beforeDestroy() {
    console.log('Admin Dashboard destroyed');
  },
});
