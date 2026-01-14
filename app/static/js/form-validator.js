/**
 * FormValidator - A comprehensive form validation library
 * Features:
 * - Real-time form validation
 * - Password strength checking
 * - Email validation
 * - Inline error display
 * - Field matching (e.g., password confirmation)
 * - Accessibility support (ARIA labels and roles)
 * - Customizable validation rules
 * - Error handling
 *
 * @version 1.0.0
 * @author FormValidator Contributors
 */

class FormValidator {
  /**
   * Creates a new FormValidator instance
   * @param {HTMLFormElement|string} form - DOM element or selector of the form to validate
   * @param {Object} options - Configuration options
   */
  constructor(form, options = {}) {
    this.form = typeof form === 'string' ? document.querySelector(form) : form;
    
    if (!this.form || this.form.tagName !== 'FORM') {
      throw new Error('Invalid form element provided');
    }

    // Configuration
    this.options = {
      validateOnChange: options.validateOnChange !== false,
      validateOnBlur: options.validateOnBlur !== false,
      validateOnSubmit: options.validateOnSubmit !== false,
      errorClass: options.errorClass || 'is-invalid',
      successClass: options.successClass || 'is-valid',
      errorMessageClass: options.errorMessageClass || 'form-error-message',
      errorContainerClass: options.errorContainerClass || 'form-errors',
      realTimeValidation: options.realTimeValidation !== false,
      showErrorMessages: options.showErrorMessages !== false,
      accessibilityMode: options.accessibilityMode !== false,
      debounceDelay: options.debounceDelay || 300,
      customErrorMessages: options.customErrorMessages || {},
      customRules: options.customRules || {},
      onFieldValidate: options.onFieldValidate || null,
      onFormValidate: options.onFormValidate || null,
    };

    // State
    this.fields = new Map();
    this.validationRules = { ...this.getDefaultRules(), ...this.options.customRules };
    this.errors = new Map();
    this.fieldDebouncers = new Map();
    this.isValidating = false;

    this.init();
  }

  /**
   * Initialize the form validator
   */
  init() {
    this.cacheFormFields();
    this.attachEventListeners();
    this.setupAccessibility();
  }

  /**
   * Cache all form fields for validation
   */
  cacheFormFields() {
    const inputs = this.form.querySelectorAll(
      'input[type="text"], input[type="email"], input[type="password"], input[type="number"], input[type="tel"], input[type="url"], textarea, select'
    );

    inputs.forEach(field => {
      const name = field.getAttribute('name');
      if (name) {
        this.fields.set(name, {
          element: field,
          type: field.getAttribute('type') || field.tagName.toLowerCase(),
          rules: this.extractFieldRules(field),
          errorElement: null,
          isValid: true,
        });
      }
    });
  }

  /**
   * Extract validation rules from field attributes
   * @param {HTMLElement} field - Form field element
   * @returns {Object} Validation rules for the field
   */
  extractFieldRules(field) {
    const rules = {};
    const dataRules = field.getAttribute('data-rules');

    if (dataRules) {
      dataRules.split('|').forEach(rule => {
        const [ruleName, ruleValue] = rule.split(':');
        rules[ruleName.trim()] = ruleValue ? ruleValue.trim() : true;
      });
    }

    // Extract HTML5 validation attributes
    if (field.hasAttribute('required')) {
      rules.required = true;
    }
    if (field.hasAttribute('pattern')) {
      rules.pattern = field.getAttribute('pattern');
    }
    if (field.hasAttribute('minlength')) {
      rules.minlength = parseInt(field.getAttribute('minlength'), 10);
    }
    if (field.hasAttribute('maxlength')) {
      rules.maxlength = parseInt(field.getAttribute('maxlength'), 10);
    }
    if (field.hasAttribute('min')) {
      rules.min = parseInt(field.getAttribute('min'), 10);
    }
    if (field.hasAttribute('max')) {
      rules.max = parseInt(field.getAttribute('max'), 10);
    }

    return rules;
  }

  /**
   * Attach event listeners to form fields
   */
  attachEventListeners() {
    this.fields.forEach((fieldData, fieldName) => {
      const { element } = fieldData;

      if (this.options.validateOnChange) {
        element.addEventListener('input', () => {
          this.validateFieldDebounced(fieldName);
        });
      }

      if (this.options.validateOnBlur) {
        element.addEventListener('blur', () => {
          this.validateField(fieldName);
        });
      }

      if (this.options.validateOnSubmit) {
        element.addEventListener('focus', () => {
          this.clearFieldErrors(fieldName);
        });
      }
    });

    if (this.options.validateOnSubmit) {
      this.form.addEventListener('submit', (e) => {
        e.preventDefault();
        this.validateForm();
      });
    }
  }

  /**
   * Setup accessibility features
   */
  setupAccessibility() {
    if (!this.options.accessibilityMode) return;

    this.fields.forEach((fieldData, fieldName) => {
      const { element } = fieldData;

      // Add ARIA attributes
      if (!element.getAttribute('aria-label')) {
        const label = this.form.querySelector(`label[for="${element.id}"]`);
        if (label) {
          element.setAttribute('aria-labelledby', `label-${fieldName}`);
          label.id = `label-${fieldName}`;
        }
      }

      // Add error message container with ARIA live region
      const errorContainer = document.createElement('div');
      errorContainer.id = `error-${fieldName}`;
      errorContainer.className = this.options.errorMessageClass;
      errorContainer.setAttribute('aria-live', 'polite');
      errorContainer.setAttribute('aria-atomic', 'true');
      errorContainer.setAttribute('role', 'alert');
      errorContainer.style.display = 'none';

      element.parentElement.appendChild(errorContainer);
      fieldData.errorElement = errorContainer;

      // Set aria-invalid initially
      element.setAttribute('aria-invalid', 'false');
      element.setAttribute('aria-describedby', `error-${fieldName}`);
    });
  }

  /**
   * Validate a field with debouncing
   * @param {string} fieldName - Name of the field to validate
   */
  validateFieldDebounced(fieldName) {
    if (this.fieldDebouncers.has(fieldName)) {
      clearTimeout(this.fieldDebouncers.get(fieldName));
    }

    const timeout = setTimeout(() => {
      this.validateField(fieldName);
    }, this.options.debounceDelay);

    this.fieldDebouncers.set(fieldName, timeout);
  }

  /**
   * Validate a single field
   * @param {string} fieldName - Name of the field to validate
   * @returns {boolean} Validation result
   */
  validateField(fieldName) {
    const fieldData = this.fields.get(fieldName);
    if (!fieldData) return true;

    const { element, rules } = fieldData;
    const value = element.value.trim();
    const fieldErrors = [];

    // Validate each rule for the field
    for (const [ruleName, ruleValue] of Object.entries(rules)) {
      if (this.validationRules[ruleName]) {
        const result = this.validationRules[ruleName](value, ruleValue, element, this.form);
        if (result !== true) {
          fieldErrors.push(result);
        }
      }
    }

    // Update field state
    const isValid = fieldErrors.length === 0;
    fieldData.isValid = isValid;
    this.errors.set(fieldName, fieldErrors);

    // Update UI
    this.updateFieldUI(fieldName, isValid, fieldErrors);

    // Call callback
    if (this.options.onFieldValidate) {
      this.options.onFieldValidate(fieldName, isValid, fieldErrors);
    }

    return isValid;
  }

  /**
   * Update field UI with validation state
   * @param {string} fieldName - Name of the field
   * @param {boolean} isValid - Whether the field is valid
   * @param {Array} errors - Array of error messages
   */
  updateFieldUI(fieldName, isValid, errors) {
    const fieldData = this.fields.get(fieldName);
    if (!fieldData) return;

    const { element, errorElement } = fieldData;

    // Update field classes
    element.classList.toggle(this.options.errorClass, !isValid);
    element.classList.toggle(this.options.successClass, isValid);

    // Update ARIA attributes
    if (this.options.accessibilityMode) {
      element.setAttribute('aria-invalid', !isValid);
    }

    // Update error messages
    if (this.options.showErrorMessages && errorElement) {
      if (isValid) {
        errorElement.textContent = '';
        errorElement.style.display = 'none';
      } else {
        errorElement.innerHTML = errors.map(error => `<p>${this.escapeHtml(error)}</p>`).join('');
        errorElement.style.display = 'block';
      }
    }
  }

  /**
   * Validate the entire form
   * @returns {boolean} Whether the form is valid
   */
  async validateForm() {
    this.isValidating = true;
    let isFormValid = true;

    // Validate all fields
    for (const fieldName of this.fields.keys()) {
      const isFieldValid = this.validateField(fieldName);
      isFormValid = isFormValid && isFieldValid;
    }

    this.isValidating = false;

    // Call callback
    if (this.options.onFormValidate) {
      this.options.onFormValidate(isFormValid, this.getFormData(), this.errors);
    }

    return isFormValid;
  }

  /**
   * Clear errors for a specific field
   * @param {string} fieldName - Name of the field
   */
  clearFieldErrors(fieldName) {
    const fieldData = this.fields.get(fieldName);
    if (!fieldData) return;

    this.errors.delete(fieldName);
    this.updateFieldUI(fieldName, true, []);
  }

  /**
   * Clear all form errors
   */
  clearAllErrors() {
    this.errors.clear();
    this.fields.forEach((fieldData, fieldName) => {
      this.updateFieldUI(fieldName, true, []);
    });
  }

  /**
   * Get form data as an object
   * @returns {Object} Form data
   */
  getFormData() {
    const data = {};
    this.fields.forEach((fieldData, fieldName) => {
      data[fieldName] = fieldData.element.value;
    });
    return data;
  }

  /**
   * Get all validation errors
   * @returns {Object} Object with field names as keys and error arrays as values
   */
  getErrors() {
    const errors = {};
    this.errors.forEach((fieldErrors, fieldName) => {
      if (fieldErrors.length > 0) {
        errors[fieldName] = fieldErrors;
      }
    });
    return errors;
  }

  /**
   * Check if form is valid
   * @returns {boolean} Form validity state
   */
  isValid() {
    let valid = true;
    this.fields.forEach((fieldData) => {
      if (!fieldData.isValid) {
        valid = false;
      }
    });
    return valid;
  }

  /**
   * Get default validation rules
   * @returns {Object} Default validation rules
   */
  getDefaultRules() {
    return {
      required: (value) => {
        if (!value || value === '') {
          return this.getErrorMessage('required', 'This field is required');
        }
        return true;
      },

      email: (value) => {
        if (!value) return true;
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) {
          return this.getErrorMessage('email', 'Please enter a valid email address');
        }
        return true;
      },

      password: (value) => {
        if (!value) return true;
        if (value.length < 8) {
          return this.getErrorMessage('password', 'Password must be at least 8 characters long');
        }
        return true;
      },

      passwordStrength: (value) => {
        if (!value) return true;
        const strength = this.checkPasswordStrength(value);
        if (strength.score < 2) {
          return this.getErrorMessage('passwordStrength', `Password is too weak. ${strength.feedback}`);
        }
        return true;
      },

      match: (value, matchFieldName, element, form) => {
        if (!value) return true;
        const matchField = form.querySelector(`[name="${matchFieldName}"]`);
        if (!matchField || matchField.value !== value) {
          return this.getErrorMessage('match', `This field must match ${matchFieldName}`);
        }
        return true;
      },

      minlength: (value, minLength) => {
        if (!value) return true;
        if (value.length < minLength) {
          return this.getErrorMessage('minlength', `Minimum length is ${minLength} characters`);
        }
        return true;
      },

      maxlength: (value, maxLength) => {
        if (!value) return true;
        if (value.length > maxLength) {
          return this.getErrorMessage('maxlength', `Maximum length is ${maxLength} characters`);
        }
        return true;
      },

      pattern: (value, pattern) => {
        if (!value) return true;
        const regex = new RegExp(pattern);
        if (!regex.test(value)) {
          return this.getErrorMessage('pattern', 'Invalid format');
        }
        return true;
      },

      url: (value) => {
        if (!value) return true;
        try {
          new URL(value);
          return true;
        } catch {
          return this.getErrorMessage('url', 'Please enter a valid URL');
        }
      },

      phone: (value) => {
        if (!value) return true;
        const phoneRegex = /^[\d\s\-\+\(\)]+$/;
        if (!phoneRegex.test(value) || value.replace(/\D/g, '').length < 10) {
          return this.getErrorMessage('phone', 'Please enter a valid phone number');
        }
        return true;
      },

      number: (value) => {
        if (!value) return true;
        if (isNaN(value)) {
          return this.getErrorMessage('number', 'Please enter a valid number');
        }
        return true;
      },

      min: (value, minValue) => {
        if (!value) return true;
        if (parseFloat(value) < parseFloat(minValue)) {
          return this.getErrorMessage('min', `Minimum value is ${minValue}`);
        }
        return true;
      },

      max: (value, maxValue) => {
        if (!value) return true;
        if (parseFloat(value) > parseFloat(maxValue)) {
          return this.getErrorMessage('max', `Maximum value is ${maxValue}`);
        }
        return true;
      },

      alphanumeric: (value) => {
        if (!value) return true;
        const alphanumericRegex = /^[a-zA-Z0-9]+$/;
        if (!alphanumericRegex.test(value)) {
          return this.getErrorMessage('alphanumeric', 'Only letters and numbers are allowed');
        }
        return true;
      },

      alpha: (value) => {
        if (!value) return true;
        const alphaRegex = /^[a-zA-Z\s]+$/;
        if (!alphaRegex.test(value)) {
          return this.getErrorMessage('alpha', 'Only letters are allowed');
        }
        return true;
      },
    };
  }

  /**
   * Check password strength
   * @param {string} password - Password to check
   * @returns {Object} Password strength info with score and feedback
   */
  checkPasswordStrength(password) {
    let score = 0;
    const feedback = [];

    // Length checks
    if (password.length >= 8) score++;
    if (password.length >= 12) score++;
    if (password.length >= 16) score++;

    // Character type checks
    if (/[a-z]/.test(password)) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/\d/.test(password)) score++;
    if (/[^a-zA-Z0-9]/.test(password)) score++;

    // Feedback
    if (!/[A-Z]/.test(password)) feedback.push('Add uppercase letters.');
    if (!/[a-z]/.test(password)) feedback.push('Add lowercase letters.');
    if (!/\d/.test(password)) feedback.push('Add numbers.');
    if (!/[^a-zA-Z0-9]/.test(password)) feedback.push('Add special characters.');
    if (password.length < 12) feedback.push('Use at least 12 characters.');

    const strengths = ['Very Weak', 'Weak', 'Fair', 'Good', 'Strong', 'Very Strong'];
    const strengthScore = Math.min(Math.floor(score / 1.15), 5);

    return {
      score: strengthScore,
      strength: strengths[strengthScore],
      feedback: feedback.join(' '),
    };
  }

  /**
   * Get error message
   * @param {string} ruleName - Name of the validation rule
   * @param {string} defaultMessage - Default error message
   * @returns {string} Error message
   */
  getErrorMessage(ruleName, defaultMessage) {
    return this.options.customErrorMessages[ruleName] || defaultMessage;
  }

  /**
   * Escape HTML special characters
   * @param {string} html - HTML string to escape
   * @returns {string} Escaped string
   */
  escapeHtml(html) {
    const div = document.createElement('div');
    div.textContent = html;
    return div.innerHTML;
  }

  /**
   * Add a custom validation rule
   * @param {string} ruleName - Name of the rule
   * @param {Function} validationFn - Validation function
   * @param {string} errorMessage - Error message
   */
  addRule(ruleName, validationFn, errorMessage = '') {
    this.validationRules[ruleName] = (value, ruleValue, element, form) => {
      const result = validationFn(value, ruleValue, element, form);
      if (result !== true) {
        return errorMessage || result;
      }
      return true;
    };
  }

  /**
   * Remove a validation rule
   * @param {string} ruleName - Name of the rule to remove
   */
  removeRule(ruleName) {
    delete this.validationRules[ruleName];
  }

  /**
   * Reset the form
   */
  reset() {
    this.form.reset();
    this.clearAllErrors();
    this.fields.forEach((fieldData) => {
      fieldData.isValid = true;
      fieldData.element.classList.remove(this.options.errorClass, this.options.successClass);
    });
  }

  /**
   * Destroy the validator instance
   */
  destroy() {
    this.fieldDebouncers.forEach(timeout => clearTimeout(timeout));
    this.fieldDebouncers.clear();
    this.fields.clear();
    this.errors.clear();
  }
}

// Export for different module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = FormValidator;
}
