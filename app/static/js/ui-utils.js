/**
 * UI Utilities Library
 * Provides reusable UI components and helpers for the Nomad Pi application
 * Includes error handling, toast notifications, skeleton loaders, and performance helpers
 */

// ============================================================================
// ERROR HANDLING
// ============================================================================

/**
 * Custom error handler with logging and user feedback
 */
class ErrorHandler {
  constructor(options = {}) {
    this.logToConsole = options.logToConsole !== false;
    this.logToServer = options.logToServer || false;
    this.showUserMessage = options.showUserMessage !== false;
    this.errorCallbacks = [];
  }

  /**
   * Handle and log an error
   * @param {Error} error - The error object
   * @param {string} context - Context where error occurred
   * @param {Object} metadata - Additional metadata
   */
  handle(error, context = 'Unknown', metadata = {}) {
    const errorData = {
      message: error.message,
      stack: error.stack,
      context,
      timestamp: new Date().toISOString(),
      userAgent: navigator.userAgent,
      ...metadata
    };

    if (this.logToConsole) {
      console.error(`[${context}]`, error);
    }

    if (this.logToServer) {
      this.sendToServer(errorData);
    }

    if (this.showUserMessage) {
      this.showUserError(error.message, context);
    }

    // Execute registered callbacks
    this.errorCallbacks.forEach(callback => {
      try {
        callback(errorData);
      } catch (e) {
        console.error('Error in error callback:', e);
      }
    });

    return errorData;
  }

  /**
   * Register a callback to be executed when an error occurs
   */
  onError(callback) {
    this.errorCallbacks.push(callback);
    return () => {
      this.errorCallbacks = this.errorCallbacks.filter(cb => cb !== callback);
    };
  }

  /**
   * Send error to server for logging
   */
  async sendToServer(errorData) {
    try {
      await fetch('/api/errors/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(errorData)
      });
    } catch (e) {
      console.error('Failed to send error to server:', e);
    }
  }

  /**
   * Show user-friendly error message
   */
  showUserError(message, context) {
    Toast.error(`Error in ${context}: ${message}`, { duration: 5000 });
  }
}

const errorHandler = new ErrorHandler({
  logToConsole: true,
  logToServer: false,
  showUserMessage: true
});

// ============================================================================
// ENHANCED TOAST NOTIFICATIONS
// ============================================================================

/**
 * Enhanced Toast Notification System
 */
class Toast {
  static defaultOptions = {
    duration: 3000,
    position: 'top-right',
    pauseOnHover: true
  };

  static toasts = new Map();
  static toastContainer = null;

  /**
   * Initialize toast container
   */
  static init() {
    if (this.toastContainer) return;

    this.toastContainer = document.createElement('div');
    this.toastContainer.className = 'toast-container';
    this.toastContainer.setAttribute('role', 'region');
    this.toastContainer.setAttribute('aria-live', 'polite');
    document.body.appendChild(this.toastContainer);

    // Add styles if not present
    this.injectStyles();
  }

  /**
   * Show success toast
   */
  static success(message, options = {}) {
    return this.show(message, 'success', options);
  }

  /**
   * Show error toast
   */
  static error(message, options = {}) {
    return this.show(message, 'error', options);
  }

  /**
   * Show warning toast
   */
  static warning(message, options = {}) {
    return this.show(message, 'warning', options);
  }

  /**
   * Show info toast
   */
  static info(message, options = {}) {
    return this.show(message, 'info', options);
  }

  /**
   * Show loading toast
   */
  static loading(message, options = {}) {
    return this.show(message, 'loading', { ...options, duration: 0 });
  }

  /**
   * Create and display a toast
   */
  static show(message, type = 'info', options = {}) {
    this.init();

    const config = { ...this.defaultOptions, ...options };
    const toastId = `toast-${Date.now()}-${Math.random()}`;

    // Create toast element
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.id = toastId;
    toast.setAttribute('role', 'status');

    // Build toast content
    const icon = this.getIcon(type);
    toast.innerHTML = `
      <div class="toast-content">
        <div class="toast-icon">${icon}</div>
        <div class="toast-message">${this.escapeHtml(message)}</div>
        <button class="toast-close" aria-label="Close notification">&times;</button>
      </div>
    `;

    // Apply position class
    toast.classList.add(`toast-${config.position}`);

    // Handle pause on hover
    if (config.pauseOnHover) {
      let timeoutId;
      toast.addEventListener('mouseenter', () => {
        if (timeoutId) clearTimeout(timeoutId);
      });
      toast.addEventListener('mouseleave', () => {
        this.scheduleRemoval(toastId, config.duration);
      });
    }

    // Close button handler
    toast.querySelector('.toast-close').addEventListener('click', () => {
      this.remove(toastId);
    });

    // Add to container
    this.toastContainer.appendChild(toast);
    this.toasts.set(toastId, { element: toast, config });

    // Trigger animation
    setTimeout(() => toast.classList.add('toast-show'), 10);

    // Schedule removal
    if (config.duration > 0) {
      this.scheduleRemoval(toastId, config.duration);
    }

    // Return object with controls
    return {
      id: toastId,
      dismiss: () => this.remove(toastId),
      update: (newMessage) => this.update(toastId, newMessage)
    };
  }

  /**
   * Schedule toast removal
   */
  static scheduleRemoval(toastId, duration) {
    setTimeout(() => {
      this.remove(toastId);
    }, duration);
  }

  /**
   * Remove toast by ID
   */
  static remove(toastId) {
    const toast = this.toasts.get(toastId);
    if (!toast) return;

    toast.element.classList.remove('toast-show');
    setTimeout(() => {
      if (toast.element.parentNode) {
        toast.element.parentNode.removeChild(toast.element);
      }
      this.toasts.delete(toastId);
    }, 300);
  }

  /**
   * Update toast message
   */
  static update(toastId, newMessage) {
    const toast = this.toasts.get(toastId);
    if (!toast) return;

    const messageEl = toast.element.querySelector('.toast-message');
    if (messageEl) {
      messageEl.textContent = newMessage;
    }
  }

  /**
   * Get icon for toast type
   */
  static getIcon(type) {
    const icons = {
      success: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M16.707 5.293l-8 8a1 1 0 01-1.414 0l-4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
      error: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="9" stroke="currentColor" stroke-width="2"/><path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
      warning: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 1l9 16H1L10 1z" stroke="currentColor" stroke-width="2"/><circle cx="10" cy="14" r="1" fill="currentColor"/><path d="M10 6v5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
      info: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="9" stroke="currentColor" stroke-width="2"/><circle cx="10" cy="6" r="1" fill="currentColor"/><path d="M10 9v5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
      loading: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" class="toast-spinner"><circle cx="10" cy="10" r="9" stroke="currentColor" stroke-width="2" fill="none"/><path d="M10 1a9 9 0 019 9" stroke="currentColor" stroke-width="2" fill="none"/></svg>'
    };
    return icons[type] || icons.info;
  }

  /**
   * Escape HTML special characters
   */
  static escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Inject toast styles
   */
  static injectStyles() {
    if (document.getElementById('toast-styles')) return;

    const style = document.createElement('style');
    style.id = 'toast-styles';
    style.textContent = `
      .toast-container {
        position: fixed;
        z-index: 9999;
        pointer-events: none;
      }

      .toast {
        pointer-events: auto;
        margin-bottom: 12px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        background: white;
        padding: 16px;
        display: flex;
        align-items: center;
        gap: 12px;
        opacity: 0;
        transform: translateY(-20px);
        transition: all 0.3s ease;
        max-width: 400px;
        min-width: 300px;
      }

      .toast.toast-show {
        opacity: 1;
        transform: translateY(0);
      }

      .toast-top-right {
        top: 20px;
        right: 20px;
      }

      .toast-top-left {
        top: 20px;
        left: 20px;
      }

      .toast-bottom-right {
        bottom: 20px;
        right: 20px;
      }

      .toast-bottom-left {
        bottom: 20px;
        left: 20px;
      }

      .toast-success {
        border-left: 4px solid #10b981;
      }

      .toast-success .toast-icon {
        color: #10b981;
      }

      .toast-error {
        border-left: 4px solid #ef4444;
      }

      .toast-error .toast-icon {
        color: #ef4444;
      }

      .toast-warning {
        border-left: 4px solid #f59e0b;
      }

      .toast-warning .toast-icon {
        color: #f59e0b;
      }

      .toast-info {
        border-left: 4px solid #3b82f6;
      }

      .toast-info .toast-icon {
        color: #3b82f6;
      }

      .toast-loading {
        border-left: 4px solid #8b5cf6;
      }

      .toast-loading .toast-icon {
        color: #8b5cf6;
      }

      .toast-content {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;
      }

      .toast-icon {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .toast-spinner {
        animation: spin 1s linear infinite;
      }

      @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }

      .toast-message {
        flex: 1;
        color: #333;
        font-size: 14px;
        line-height: 1.5;
        word-break: break-word;
      }

      .toast-close {
        flex-shrink: 0;
        background: none;
        border: none;
        color: #999;
        cursor: pointer;
        font-size: 24px;
        padding: 0;
        line-height: 1;
        transition: color 0.2s;
      }

      .toast-close:hover {
        color: #333;
      }
    `;

    document.head.appendChild(style);
  }
}

// ============================================================================
// SKELETON LOADERS
// ============================================================================

/**
 * Skeleton Loader Component
 */
class SkeletonLoader {
  /**
   * Create a skeleton loader element
   * @param {Object} options - Configuration options
   */
  static create(options = {}) {
    const {
      type = 'text',
      lines = 3,
      width = '100%',
      height = '16px',
      className = '',
      animated = true
    } = options;

    const skeleton = document.createElement('div');
    skeleton.className = `skeleton skeleton-${type}${animated ? ' skeleton-animated' : ''}${className ? ' ' + className : ''}`;

    switch (type) {
      case 'text':
        skeleton.innerHTML = this.createTextSkeleton(lines, width, height);
        break;
      case 'card':
        skeleton.innerHTML = this.createCardSkeleton();
        break;
      case 'avatar':
        skeleton.innerHTML = this.createAvatarSkeleton(width);
        break;
      case 'table':
        skeleton.innerHTML = this.createTableSkeleton();
        break;
      case 'image':
        skeleton.innerHTML = this.createImageSkeleton(width, height);
        break;
      default:
        skeleton.style.width = width;
        skeleton.style.height = height;
    }

    // Inject styles if not present
    this.injectStyles();

    return skeleton;
  }

  /**
   * Create text skeleton
   */
  static createTextSkeleton(lines, width, height) {
    let html = '';
    for (let i = 0; i < lines; i++) {
      const lineWidth = i === lines - 1 ? '70%' : '100%';
      html += `<div class="skeleton-line" style="width: ${lineWidth}; height: ${height}; margin-bottom: 8px;"></div>`;
    }
    return html;
  }

  /**
   * Create card skeleton
   */
  static createCardSkeleton() {
    return `
      <div style="padding: 16px; border-radius: 8px; background: #f3f4f6;">
        <div class="skeleton-line" style="width: 100%; height: 24px; margin-bottom: 16px;"></div>
        <div class="skeleton-line" style="width: 100%; height: 16px; margin-bottom: 8px;"></div>
        <div class="skeleton-line" style="width: 85%; height: 16px; margin-bottom: 16px;"></div>
        <div class="skeleton-line" style="width: 150px; height: 36px; border-radius: 4px;"></div>
      </div>
    `;
  }

  /**
   * Create avatar skeleton
   */
  static createAvatarSkeleton(size = '40px') {
    return `<div class="skeleton-line" style="width: ${size}; height: ${size}; border-radius: 50%;"></div>`;
  }

  /**
   * Create table skeleton
   */
  static createTableSkeleton() {
    let rows = '';
    for (let i = 0; i < 5; i++) {
      rows += `
        <tr>
          <td><div class="skeleton-line" style="width: 100%; height: 16px;"></div></td>
          <td><div class="skeleton-line" style="width: 100%; height: 16px;"></div></td>
          <td><div class="skeleton-line" style="width: 100%; height: 16px;"></div></td>
        </tr>
      `;
    }
    return `<table style="width: 100%;"><tbody>${rows}</tbody></table>`;
  }

  /**
   * Create image skeleton
   */
  static createImageSkeleton(width = '100%', height = '200px') {
    return `<div class="skeleton-line" style="width: ${width}; height: ${height}; border-radius: 8px;"></div>`;
  }

  /**
   * Inject skeleton styles
   */
  static injectStyles() {
    if (document.getElementById('skeleton-styles')) return;

    const style = document.createElement('style');
    style.id = 'skeleton-styles';
    style.textContent = `
      .skeleton {
        background-color: #f3f4f6;
        border-radius: 4px;
      }

      .skeleton-line {
        background-color: #e5e7eb;
        border-radius: 4px;
        display: block;
      }

      .skeleton-animated {
        animation: skeleton-loading 1.5s infinite;
      }

      .skeleton-animated .skeleton-line {
        animation: skeleton-loading 1.5s infinite;
      }

      @keyframes skeleton-loading {
        0% {
          background-color: #f3f4f6;
        }
        50% {
          background-color: #e5e7eb;
        }
        100% {
          background-color: #f3f4f6;
        }
      }

      .skeleton-text .skeleton-line {
        display: block;
      }

      .skeleton-card {
        border-radius: 8px;
        overflow: hidden;
      }

      .skeleton-avatar {
        display: inline-block;
      }
    `;

    document.head.appendChild(style);
  }

  /**
   * Replace element with skeleton
   */
  static showIn(element, options = {}) {
    const skeleton = this.create(options);
    element.innerHTML = '';
    element.appendChild(skeleton);
  }

  /**
   * Hide skeleton
   */
  static hideIn(element) {
    const skeleton = element.querySelector('.skeleton');
    if (skeleton) {
      skeleton.remove();
    }
  }
}

// ============================================================================
// PERFORMANCE HELPERS
// ============================================================================

/**
 * Debounce function - delays function execution until a wait period passes
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @param {Object} options - Options (leading, trailing, maxWait)
 */
function debounce(func, wait, options = {}) {
  let timeout, args, context, timestamp, result;
  let lastCalled = 0;
  let lastInvokeTime = 0;

  const leading = options.leading || false;
  const trailing = options.trailing !== false;
  const maxWait = options.maxWait;

  function invokeFunc(time) {
    const args = lastArgs;
    const context = lastContext;

    lastArgs = lastContext = null;
    lastInvokeTime = time;
    result = func.apply(context, args);
    return result;
  }

  function leadingEdge(time) {
    lastInvokeTime = time;
    timeout = setTimeout(timerExpired, wait);
    return leading ? invokeFunc(time) : result;
  }

  function trailingEdge(time) {
    timeout = null;
    if (trailing && lastArgs) {
      return invokeFunc(time);
    }
    lastArgs = lastContext = null;
    return result;
  }

  function timerExpired() {
    const time = Date.now();
    if (shouldInvoke(time)) {
      return trailingEdge(time);
    }
    const timeWaiting = time - lastInvokeTime;
    const timeToWait = wait - timeWaiting;
    timeout = setTimeout(timerExpired, timeToWait);
  }

  function shouldInvoke(time) {
    if (timeout === null) {
      return true;
    }
    const timeSinceLastCall = time - lastCalled;
    const timeSinceLastInvoke = time - lastInvokeTime;
    return timeSinceLastCall >= wait || timeSinceLastInvoke >= maxWait;
  }

  function debounced(...args) {
    const time = Date.now();
    const isInvoking = shouldInvoke(time);

    lastArgs = args;
    lastContext = this;
    lastCalled = time;

    if (isInvoking) {
      if (timeout === null && leading) {
        return leadingEdge(time);
      }
      if (timeout) {
        clearTimeout(timeout);
      }
      timeout = setTimeout(timerExpired, wait);
    }
    return result;
  }

  debounced.cancel = function() {
    if (timeout) {
      clearTimeout(timeout);
    }
    lastInvokeTime = 0;
    lastArgs = lastContext = timeout = null;
  };

  debounced.flush = function() {
    return timeout === null ? result : trailingEdge(Date.now());
  };

  return debounced;
}

/**
 * Throttle function - limits function execution to once per wait period
 * @param {Function} func - Function to throttle
 * @param {number} wait - Wait time in milliseconds
 */
function throttle(func, wait) {
  let timeout = null;
  let previous = 0;

  return function throttled(...args) {
    const now = Date.now();
    const remaining = wait - (now - previous);

    if (remaining <= 0) {
      if (timeout) {
        clearTimeout(timeout);
        timeout = null;
      }
      previous = now;
      return func.apply(this, args);
    } else if (!timeout) {
      timeout = setTimeout(() => {
        previous = Date.now();
        timeout = null;
        func.apply(this, args);
      }, remaining);
    }
  };
}

/**
 * Request Animation Frame debounce
 */
function rafDebounce(func) {
  let frameId = null;

  const debounced = function(...args) {
    if (frameId) {
      cancelAnimationFrame(frameId);
    }
    frameId = requestAnimationFrame(() => {
      func.apply(this, args);
      frameId = null;
    });
  };

  debounced.cancel = () => {
    if (frameId) {
      cancelAnimationFrame(frameId);
      frameId = null;
    }
  };

  return debounced;
}

/**
 * Virtual Scrolling Utility
 * Renders only visible items for better performance with large lists
 */
class VirtualScroller {
  constructor(container, options = {}) {
    this.container = container;
    this.items = [];
    this.itemHeight = options.itemHeight || 50;
    this.bufferSize = options.bufferSize || 5;
    this.scrollHandler = null;

    this.visibleStart = 0;
    this.visibleEnd = 0;

    this.viewport = document.createElement('div');
    this.viewport.style.overflow = 'auto';
    this.viewport.style.height = options.height || '100%';

    this.content = document.createElement('div');
    this.viewport.appendChild(this.content);
    this.container.appendChild(this.viewport);

    this.setupScrollListener();
  }

  /**
   * Set items to be rendered
   */
  setItems(items) {
    this.items = items;
    this.content.style.height = items.length * this.itemHeight + 'px';
    this.updateVisibleItems();
  }

  /**
   * Setup scroll event listener
   */
  setupScrollListener() {
    this.scrollHandler = rafDebounce(() => {
      this.updateVisibleItems();
    });

    this.viewport.addEventListener('scroll', this.scrollHandler);
  }

  /**
   * Update visible items based on scroll position
   */
  updateVisibleItems() {
    const scrollTop = this.viewport.scrollTop;
    const viewportHeight = this.viewport.clientHeight;

    this.visibleStart = Math.max(0, Math.floor(scrollTop / this.itemHeight) - this.bufferSize);
    this.visibleEnd = Math.min(
      this.items.length,
      Math.ceil((scrollTop + viewportHeight) / this.itemHeight) + this.bufferSize
    );

    this.render();
  }

  /**
   * Render visible items
   */
  render() {
    const fragment = document.createDocumentFragment();

    // Add top spacer
    if (this.visibleStart > 0) {
      const spacer = document.createElement('div');
      spacer.style.height = this.visibleStart * this.itemHeight + 'px';
      fragment.appendChild(spacer);
    }

    // Render visible items
    for (let i = this.visibleStart; i < this.visibleEnd; i++) {
      const item = this.items[i];
      const element = this.renderItem(item, i);
      element.style.height = this.itemHeight + 'px';
      fragment.appendChild(element);
    }

    // Add bottom spacer
    if (this.visibleEnd < this.items.length) {
      const spacer = document.createElement('div');
      spacer.style.height = (this.items.length - this.visibleEnd) * this.itemHeight + 'px';
      fragment.appendChild(spacer);
    }

    this.content.innerHTML = '';
    this.content.appendChild(fragment);
  }

  /**
   * Render a single item - override this method
   */
  renderItem(item, index) {
    const element = document.createElement('div');
    element.className = 'virtual-item';
    element.textContent = `Item ${index}`;
    return element;
  }

  /**
   * Destroy the scroller
   */
  destroy() {
    if (this.scrollHandler) {
      this.viewport.removeEventListener('scroll', this.scrollHandler);
      this.scrollHandler.cancel();
    }
    this.container.removeChild(this.viewport);
  }

  /**
   * Scroll to item
   */
  scrollToItem(index) {
    const scrollTop = index * this.itemHeight;
    this.viewport.scrollTop = scrollTop;
  }
}

/**
 * Intersection Observer utility for lazy loading
 */
class LazyLoader {
  constructor(options = {}) {
    this.options = {
      root: options.root || null,
      rootMargin: options.rootMargin || '100px',
      threshold: options.threshold || 0.1,
      onVisible: options.onVisible || (() => {})
    };

    this.observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          this.options.onVisible(entry.target);
          this.observer.unobserve(entry.target);
        }
      });
    }, {
      root: this.options.root,
      rootMargin: this.options.rootMargin,
      threshold: this.options.threshold
    });
  }

  /**
   * Observe an element
   */
  observe(element) {
    this.observer.observe(element);
  }

  /**
   * Stop observing an element
   */
  unobserve(element) {
    this.observer.unobserve(element);
  }

  /**
   * Disconnect observer
   */
  disconnect() {
    this.observer.disconnect();
  }
}

// ============================================================================
// UTILITY HELPERS
// ============================================================================

/**
 * DOM utilities
 */
const DOM = {
  /**
   * Create element with attributes and content
   */
  create(tag, options = {}) {
    const element = document.createElement(tag);

    if (options.className) {
      element.className = options.className;
    }

    if (options.attrs) {
      Object.entries(options.attrs).forEach(([key, value]) => {
        element.setAttribute(key, value);
      });
    }

    if (options.styles) {
      Object.entries(options.styles).forEach(([key, value]) => {
        element.style[key] = value;
      });
    }

    if (options.html) {
      element.innerHTML = options.html;
    } else if (options.text) {
      element.textContent = options.text;
    }

    if (options.children) {
      options.children.forEach(child => {
        if (typeof child === 'string') {
          element.appendChild(document.createTextNode(child));
        } else {
          element.appendChild(child);
        }
      });
    }

    return element;
  },

  /**
   * Query selector helper
   */
  query(selector, parent = document) {
    return parent.querySelector(selector);
  },

  /**
   * Query all helper
   */
  queryAll(selector, parent = document) {
    return Array.from(parent.querySelectorAll(selector));
  },

  /**
   * Add event listener with delegation
   */
  on(element, event, selector, handler) {
    element.addEventListener(event, (e) => {
      if (e.target.matches(selector)) {
        handler.call(e.target, e);
      }
    });
  }
};

/**
 * Performance monitoring
 */
const Performance = {
  /**
   * Measure function execution time
   */
  measure(name, func) {
    const start = performance.now();
    const result = func();
    const duration = performance.now() - start;
    console.log(`[Performance] ${name}: ${duration.toFixed(2)}ms`);
    return result;
  },

  /**
   * Get performance metrics
   */
  getMetrics() {
    if (!window.performance || !window.performance.timing) {
      return null;
    }

    const timing = window.performance.timing;
    return {
      dns: timing.domainLookupEnd - timing.domainLookupStart,
      tcp: timing.connectEnd - timing.connectStart,
      ttfb: timing.responseStart - timing.navigationStart,
      download: timing.responseEnd - timing.responseStart,
      domParse: timing.domInteractive - timing.domLoading,
      resources: timing.domComplete - timing.domLoading,
      domComplete: timing.domComplete - timing.navigationStart,
      loadComplete: timing.loadEventEnd - timing.navigationStart
    };
  }
};

// ============================================================================
// EXPORTS
// ============================================================================

// Export for use as modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    ErrorHandler,
    errorHandler,
    Toast,
    SkeletonLoader,
    debounce,
    throttle,
    rafDebounce,
    VirtualScroller,
    LazyLoader,
    DOM,
    Performance
  };
}
