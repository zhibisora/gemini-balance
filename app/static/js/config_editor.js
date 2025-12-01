// Constants
const SENSITIVE_INPUT_CLASS = "sensitive-input";
const ARRAY_ITEM_CLASS = "array-item";
const ARRAY_INPUT_CLASS = "array-input";
const CUSTOM_HEADER_ITEM_CLASS = "custom-header-item";
const CUSTOM_HEADER_KEY_INPUT_CLASS = "custom-header-key-input";
const CUSTOM_HEADER_VALUE_INPUT_CLASS = "custom-header-value-input";
const SHOW_CLASS = "show"; // For modals
const API_KEY_REGEX = /AIzaSy\S{33}/g;
const MASKED_VALUE = "••••••••";

// API Keys Pagination Constants
const API_KEYS_PER_PAGE = 20;
let currentApiKeyPage = 1;
let totalApiKeyPages = 1;
let allApiKeys = []; // Stores all API keys
let filteredApiKeys = []; // Stores filtered API keys for display

// DOM Elements - Global Scope for frequently accessed elements
let apiKeyModal, apiKeyBulkInput, apiKeySearchInput, bulkDeleteApiKeyModal, bulkDeleteApiKeyInput, resetConfirmModal, configForm, modelHelperModal, modelHelperTitleElement, modelHelperSearchInput, modelHelperListContainer;

// Model Helper Modal Elements
let cachedModelsList = null;
let currentModelHelperTarget = null; // { type: 'input', target: element }

// Modal Control Functions
function openModal(modalElement) {
  if (modalElement) {
    modalElement.classList.add(SHOW_CLASS);
  }
}

function closeModal(modalElement) {
  if (modalElement) {
    modalElement.classList.remove(SHOW_CLASS);
  }
}

document.addEventListener("DOMContentLoaded", function () {
  // Assign DOM Elements
  apiKeyModal = document.getElementById("apiKeyModal");
  apiKeyBulkInput = document.getElementById("apiKeyBulkInput");
  apiKeySearchInput = document.getElementById("apiKeySearchInput");
  bulkDeleteApiKeyModal = document.getElementById("bulkDeleteApiKeyModal");
  bulkDeleteApiKeyInput = document.getElementById("bulkDeleteApiKeyInput");
  resetConfirmModal = document.getElementById("resetConfirmModal");
  configForm = document.getElementById("configForm");
  modelHelperModal = document.getElementById("modelHelperModal");
  modelHelperTitleElement = document.getElementById("modelHelperTitle");
  modelHelperSearchInput = document.getElementById("modelHelperSearchInput");
  modelHelperListContainer = document.getElementById("modelHelperListContainer");

  // Initialize configuration
  initConfig();

  // Tab switching
  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", function (e) {
      e.stopPropagation();
      switchTab(this.getAttribute("data-tab"));
    });
  });

  // The original JS had a section for upload provider switching, which is not in the HTML.
  // I am removing it to match the HTML.
  /*
  // Upload provider switching
  const uploadProviderSelect = document.getElementById("UPLOAD_PROVIDER");
  if (uploadProviderSelect) {
    uploadProviderSelect.addEventListener("change", function () {
      toggleProviderConfig(this.value);
    });
  }
  */

  // The original JS had a section for check interval input control, which is not needed as the HTML input type="number" handles it.

  // Toggle switch events
  const toggleSwitches = document.querySelectorAll(".toggle-switch");
  toggleSwitches.forEach((toggleSwitch) => {
    toggleSwitch.addEventListener("click", function (e) {
      e.stopPropagation();
      const checkbox = this.querySelector('input[type="checkbox"]');
      if (checkbox) {
        checkbox.checked = !checkbox.checked;
      }
    });
  });

  // Main Action Buttons
  document.getElementById("saveBtn")?.addEventListener("click", saveConfig);
  document.getElementById("resetBtn")?.addEventListener("click", resetConfig);

  // Scroll buttons
  window.addEventListener("scroll", toggleScrollButtons);

  // API Key Modal Elements and Events
  document.getElementById("addApiKeyBtn")?.addEventListener("click", () => {
    openModal(apiKeyModal);
    if (apiKeyBulkInput) apiKeyBulkInput.value = "";
  });
  document.getElementById("closeApiKeyModalBtn")?.addEventListener("click", () => closeModal(apiKeyModal));
  document.getElementById("cancelAddApiKeyBtn")?.addEventListener("click", () => closeModal(apiKeyModal));
  document.getElementById("confirmAddApiKeyBtn")?.addEventListener("click", handleBulkAddApiKeys);
  apiKeySearchInput?.addEventListener("input", handleApiKeySearch);

  // API Key Pagination Event Listeners
  document.getElementById("apiKeyPrevBtn")?.addEventListener("click", prevApiKeyPage);
  document.getElementById("apiKeyNextBtn")?.addEventListener("click", nextApiKeyPage);

  // Bulk Delete API Key Modal Elements and Events
  document.getElementById("bulkDeleteApiKeyBtn")?.addEventListener("click", () => {
    openModal(bulkDeleteApiKeyModal);
    if (bulkDeleteApiKeyInput) bulkDeleteApiKeyInput.value = "";
  });
  document.getElementById("closeBulkDeleteModalBtn")?.addEventListener("click", () => closeModal(bulkDeleteApiKeyModal));
  document.getElementById("cancelBulkDeleteApiKeyBtn")?.addEventListener("click", () => closeModal(bulkDeleteApiKeyModal));
  document.getElementById("confirmBulkDeleteApiKeyBtn")?.addEventListener("click", handleBulkDeleteApiKeys);

  // Reset Confirmation Modal Elements and Events
  document.getElementById("closeResetModalBtn")?.addEventListener("click", () => closeModal(resetConfirmModal));
  document.getElementById("cancelResetBtn")?.addEventListener("click", () => closeModal(resetConfirmModal));
  document.getElementById("confirmResetBtn")?.addEventListener("click", () => {
    closeModal(resetConfirmModal);
    executeReset();
  });

  // Click outside modal to close
  window.addEventListener("click", (event) => {
    [apiKeyModal, resetConfirmModal, bulkDeleteApiKeyModal, modelHelperModal].forEach((modal) => {
      if (event.target === modal) {
        closeModal(modal);
      }
    });
  });

  // Authentication token generation button
  const generateAuthTokenBtn = document.getElementById("generateAuthTokenBtn");
  const authTokenInput = document.getElementById("AUTH_TOKEN");
  if (generateAuthTokenBtn && authTokenInput) {
    generateAuthTokenBtn.addEventListener("click", function () {
      const newToken = generateRandomToken();
      authTokenInput.value = newToken;
      if (authTokenInput.classList.contains(SENSITIVE_INPUT_CLASS)) {
        authTokenInput.dispatchEvent(new Event("focusout", { bubbles: true, cancelable: true }));
      }
      showNotification("已生成新认证令牌", "success");
    });
  }

  // Event delegation for dynamically added remove buttons and generate token buttons within array items
  configForm?.addEventListener("click", function (event) {
      const target = event.target;
      const removeButton = target.closest(".remove-btn");
      const generateButton = target.closest(".generate-btn");

      if (removeButton && removeButton.closest(`.${ARRAY_ITEM_CLASS}`)) {
        const arrayItem = removeButton.closest(`.${ARRAY_ITEM_CLASS}`);
        const parentContainer = arrayItem.parentElement;
        const key = parentContainer.id.replace("_container", "");

        if (key === "API_KEYS") {
          const keyToRemove = arrayItem.querySelector(`.${ARRAY_INPUT_CLASS}`).getAttribute('data-real-value');
          allApiKeys = allApiKeys.filter(k => k !== keyToRemove);
          filteredApiKeys = filteredApiKeys.filter(k => k !== keyToRemove);
          renderApiKeyPage();
          updateApiKeyPagination();
        } else if (key === "CUSTOM_HEADERS") {
            arrayItem.remove();
            if (parentContainer.children.length === 0) {
                parentContainer.innerHTML = '<div class="text-gray-500 text-sm italic">添加自定义请求头，例如 X-Api-Key: your-key</div>';
            }
        } else {
          arrayItem.remove();
        }
      } else if (generateButton && generateButton.closest(`.${ARRAY_ITEM_CLASS}`)) {
        const inputField = generateButton.closest(`.${ARRAY_ITEM_CLASS}`).querySelector(`.${ARRAY_INPUT_CLASS}`);
        if (inputField) {
          const newToken = generateRandomToken();
          inputField.value = newToken;
          if (inputField.classList.contains(SENSITIVE_INPUT_CLASS)) {
            inputField.dispatchEvent(new Event("focusout", { bubbles: true, cancelable: true }));
          }
          showNotification("已生成新令牌", "success");
        }
      }
    });

  // Add Custom Header button
  const addCustomHeaderBtn = document.getElementById("addCustomHeaderBtn");
  if (addCustomHeaderBtn) {
    addCustomHeaderBtn.addEventListener("click", () => addCustomHeaderItem());
  }

  initializeSensitiveFields(); // Initialize sensitive field handling

  // Model Helper Modal Event Listeners
  document.getElementById("closeModelHelperModalBtn")?.addEventListener("click", () => closeModal(modelHelperModal));
  document.getElementById("cancelModelHelperBtn")?.addEventListener("click", () => closeModal(modelHelperModal));
  modelHelperSearchInput?.addEventListener("input", () => renderModelsInModal());

  // Add event listeners to all model helper trigger buttons
  document.querySelectorAll(".model-helper-trigger-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetInputId = btn.dataset.targetInputId;
      if (targetInputId) {
        currentModelHelperTarget = { type: "input", target: document.getElementById(targetInputId) };
        openModelHelperModal();
      }
    });
  });

  // Link enabled state of auto-delete checkboxes and selects
  const autoDeleteErrorCheckbox = document.getElementById("AUTO_DELETE_ERROR_LOGS_ENABLED");
  const autoDeleteErrorSelect = document.getElementById("AUTO_DELETE_ERROR_LOGS_DAYS");
  if(autoDeleteErrorCheckbox && autoDeleteErrorSelect) {
      autoDeleteErrorCheckbox.addEventListener('change', () => {
          autoDeleteErrorSelect.disabled = !autoDeleteErrorCheckbox.checked;
      });
  }

  const autoDeleteRequestCheckbox = document.getElementById("AUTO_DELETE_REQUEST_LOGS_ENABLED");
  const autoDeleteRequestSelect = document.getElementById("AUTO_DELETE_REQUEST_LOGS_DAYS");
  if(autoDeleteRequestCheckbox && autoDeleteRequestSelect) {
      autoDeleteRequestCheckbox.addEventListener('change', () => {
          autoDeleteRequestSelect.disabled = !autoDeleteRequestCheckbox.checked;
      });
  }
}); // <-- DOMContentLoaded end

/**
 * Initializes sensitive input field behavior (masking/unmasking).
 */
function initializeSensitiveFields() {
  if (!configForm) return;

  // Helper function: Mask field
  function maskField(field) {
    if (field.value && field.value !== MASKED_VALUE) {
      field.setAttribute("data-real-value", field.value);
      field.value = MASKED_VALUE;
    } else if (!field.value) {
      // If field value is empty string
      field.removeAttribute("data-real-value");
      // Ensure empty value doesn't show as asterisks
      if (field.value === MASKED_VALUE) field.value = "";
    }
  }

  // Helper function: Unmask field
  function unmaskField(field) {
    if (field.hasAttribute("data-real-value")) {
      field.value = field.getAttribute("data-real-value");
    }
    else if (field.value === MASKED_VALUE && !field.hasAttribute("data-real-value")) {
      field.value = "";
    }
  }

  // Initial masking for existing sensitive fields on page load
  // This function is called after populateForm and after dynamic element additions (via event delegation)
  function initialMaskAllExisting() {
    configForm.querySelectorAll(`.${SENSITIVE_INPUT_CLASS}`).forEach((field) => {
      if (field.type === "password") {
        if (field.value) field.setAttribute("data-real-value", field.value);
      } else if (field.type === "text" || field.tagName.toLowerCase() === "textarea") {
        maskField(field);
      }
    });
  }
  initialMaskAllExisting();

  configForm.addEventListener("focusin", function (event) {
    if (event.target.classList.contains(SENSITIVE_INPUT_CLASS)) {
      unmaskField(event.target);
    }
  });

  configForm.addEventListener("focusout", function (event) {
    if (event.target.classList.contains(SENSITIVE_INPUT_CLASS)) {
      maskField(event.target);
    }
  });
}

/**
 * Initializes the configuration by fetching it from the server and populating the form.
 */
async function initConfig() {
  try {
    showNotification("正在加载配置...", "info");
    const response = await fetch("/api/config");

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const config = await response.json();

    // Set defaults for missing fields
    const defaults = {
        API_KEYS: [],
        ALLOWED_TOKENS: [],
        CUSTOM_HEADERS: {},
        URL_NORMALIZATION_ENABLED: true,
        TEST_MODEL: "gemini-1.5-flash-latest",
        CHECK_INTERVAL_HOURS: 24,
        LOG_LEVEL: "INFO",
        ERROR_LOG_RECORD_REQUEST_BODY: false,
        AUTO_DELETE_ERROR_LOGS_ENABLED: true,
        AUTO_DELETE_ERROR_LOGS_DAYS: 7,
        AUTO_DELETE_REQUEST_LOGS_ENABLED: false,
        AUTO_DELETE_REQUEST_LOGS_DAYS: 30,
    };

    const finalConfig = { ...defaults, ...config };
    
    populateForm(finalConfig);
    initializeSensitiveFields();

    showNotification("配置加载成功", "success");
  } catch (error) {
    console.error("加载配置失败:", error);
    showNotification("加载配置失败: " + error.message, "error");
  }
}

/**
 * Populates the configuration form with data.
 * @param {object} config - The configuration object.
 */
function populateForm(config) {
  // Populate simple fields
  for (const [key, value] of Object.entries(config)) {
    const element = document.getElementById(key);
    if (element) {
      if (element.type === "checkbox") {
        element.checked = !!value;
      } else {
        element.value = value !== null && value !== undefined ? value : "";
      }
    }
  }

  // Populate CUSTOM_HEADERS
  const customHeadersContainer = document.getElementById(
    "CUSTOM_HEADERS_container"
  );
  let customHeadersAdded = false;
  if (
    customHeadersContainer &&
    config.CUSTOM_HEADERS &&
    typeof config.CUSTOM_HEADERS === "object"
  ) {
    for (const [key, value] of Object.entries(config.CUSTOM_HEADERS)) {
      createAndAppendCustomHeaderItem(key, value); // This function will be defined later
      customHeadersAdded = true;
    }
  }
  if (!customHeadersAdded && customHeadersContainer) {
    customHeadersContainer.innerHTML =
      '<div class="text-gray-500 text-sm italic">添加自定义请求头，例如 X-Api-Key: your-key</div>';
  }

  // Populate API_KEYS with pagination
  if (Array.isArray(config.API_KEYS)) {
    allApiKeys = config.API_KEYS.filter(key => typeof key === "string" && key.trim() !== "");
    filteredApiKeys = [...allApiKeys];
    currentApiKeyPage = 1;
    renderApiKeyPage();
    updateApiKeyPagination();
  }

  // Populate ALLOWED_TOKENS
  const allowedTokensContainer = document.getElementById("ALLOWED_TOKENS_container");
  if(allowedTokensContainer) {
    allowedTokensContainer.innerHTML = "";
    if (Array.isArray(config.ALLOWED_TOKENS)) {
        config.ALLOWED_TOKENS.forEach(token => addArrayItemWithValue("ALLOWED_TOKENS", token));
    }
  }

  // 6. Initialize upload provider
  const uploadProvider = document.getElementById("UPLOAD_PROVIDER");
  if (uploadProvider) {
    toggleProviderConfig(uploadProvider.value);
    // This function is defined below, but the HTML doesn't contain provider configs.
    // It will do nothing if no `.provider-config` elements exist.
  }

  // Handle dependent fields state
  const autoDeleteErrorCheckbox = document.getElementById("AUTO_DELETE_ERROR_LOGS_ENABLED");
  const autoDeleteErrorSelect = document.getElementById("AUTO_DELETE_ERROR_LOGS_DAYS");
  if(autoDeleteErrorCheckbox && autoDeleteErrorSelect) {
      autoDeleteErrorSelect.disabled = !autoDeleteErrorCheckbox.checked;
  }
  
  const autoDeleteRequestCheckbox = document.getElementById("AUTO_DELETE_REQUEST_LOGS_ENABLED");
  const autoDeleteRequestSelect = document.getElementById("AUTO_DELETE_REQUEST_LOGS_DAYS");
  if(autoDeleteRequestCheckbox && autoDeleteRequestSelect) {
      autoDeleteRequestSelect.disabled = !autoDeleteRequestCheckbox.checked;
  }
}

/**
 * Handles the bulk addition of API keys from the modal input.
 */
function handleBulkAddApiKeys() {
  if (!apiKeyBulkInput || !apiKeyModal) return;

  const bulkText = apiKeyBulkInput.value;
  const extractedKeys = bulkText.match(API_KEY_REGEX) || [];

  // Merge existing and new keys, ensuring uniqueness
  const combinedKeys = new Set([...allApiKeys, ...extractedKeys]);
  const uniqueKeys = Array.from(combinedKeys);

  // 更新全局密钥数组
  allApiKeys = uniqueKeys;
  
  // 更新过滤后的数组
  const searchTerm = apiKeySearchInput ? apiKeySearchInput.value.toLowerCase() : "";
  if (!searchTerm) {
    filteredApiKeys = [...allApiKeys];
  } else {
    filteredApiKeys = allApiKeys.filter(key =>
      key.toLowerCase().includes(searchTerm)
    );
  }

  // 重新渲染当前页
  renderApiKeyPage();
  updateApiKeyPagination();

  closeModal(apiKeyModal);
  showNotification(`添加/更新了 ${uniqueKeys.length} 个唯一密钥`, "success");
}

/**
 * Handles searching/filtering of API keys in the list.
 */
function handleApiKeySearch() {
  if (!apiKeySearchInput) return;

  const searchTerm = apiKeySearchInput.value.toLowerCase();
  
  // 过滤API密钥
  if (!searchTerm) {
    filteredApiKeys = [...allApiKeys];
  } else {
    filteredApiKeys = allApiKeys.filter(key =>
      key.toLowerCase().includes(searchTerm)
    );
  }

  // 重置到第一页
  currentApiKeyPage = 1;
  
  // 重新渲染当前页
  renderApiKeyPage();
  updateApiKeyPagination();
}

/**
 * 渲染当前页的API密钥
 */
function renderApiKeyPage() {
  const apiKeyContainer = document.getElementById("API_KEYS_container");
  if (!apiKeyContainer) return;

  // 清空容器
  apiKeyContainer.innerHTML = "";

  // 计算当前页的数据范围
  const startIndex = (currentApiKeyPage - 1) * API_KEYS_PER_PAGE;
  const endIndex = Math.min(startIndex + API_KEYS_PER_PAGE, filteredApiKeys.length);
  const pageKeys = filteredApiKeys.slice(startIndex, endIndex);

  // 渲染当前页的密钥
  pageKeys.forEach((key) => {
    addArrayItemWithValue("API_KEYS", key);
  });

  // 如果没有密钥，显示提示信息
  if (pageKeys.length === 0) {
    const emptyMessage = document.createElement("div");
    emptyMessage.className = "text-gray-500 text-sm italic text-center py-4";
    emptyMessage.textContent = filteredApiKeys.length === 0 ?
      (allApiKeys.length === 0 ? "暂无API密钥" : "未找到匹配的密钥") :
      "当前页无数据";
    apiKeyContainer.appendChild(emptyMessage);
  }
}

/**
 * 更新分页控件
 */
function updateApiKeyPagination() {
  totalApiKeyPages = Math.max(1, Math.ceil(filteredApiKeys.length / API_KEYS_PER_PAGE));
  
  // 确保当前页在有效范围内
  if (currentApiKeyPage > totalApiKeyPages) {
    currentApiKeyPage = totalApiKeyPages;
  }

  const paginationContainer = document.getElementById("apiKeyPagination");
  if (!paginationContainer) return;

  // 如果只有一页或没有数据，隐藏分页控件
  if (totalApiKeyPages <= 1) {
    paginationContainer.style.display = "none";
    return;
  }

  paginationContainer.style.display = "flex";

  // 更新页码信息
  const pageInfo = document.getElementById("apiKeyPageInfo");
  if (pageInfo) {
    pageInfo.textContent = `第 ${currentApiKeyPage} 页，共 ${totalApiKeyPages} 页 (${filteredApiKeys.length} 个密钥)`;
  }

  // 更新按钮状态
  const prevBtn = document.getElementById("apiKeyPrevBtn");
  const nextBtn = document.getElementById("apiKeyNextBtn");
  
  if (prevBtn) {
    prevBtn.disabled = currentApiKeyPage <= 1;
    prevBtn.className = currentApiKeyPage <= 1 ?
      "px-3 py-1 rounded bg-gray-300 text-gray-500 cursor-not-allowed" :
      "px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 cursor-pointer";
  }
  
  if (nextBtn) {
    nextBtn.disabled = currentApiKeyPage >= totalApiKeyPages;
    nextBtn.className = currentApiKeyPage >= totalApiKeyPages ?
      "px-3 py-1 rounded bg-gray-300 text-gray-500 cursor-not-allowed" :
      "px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600 cursor-pointer";
  }
}

/**
 * 跳转到指定页
 */
function goToApiKeyPage(page) {
  if (page < 1 || page > totalApiKeyPages) return;
  
  currentApiKeyPage = page;
  renderApiKeyPage();
  updateApiKeyPagination();
}

/**
 * 上一页
 */
function prevApiKeyPage() {
  if (currentApiKeyPage > 1) {
    goToApiKeyPage(currentApiKeyPage - 1);
  }
}

/**
 * 下一页
 */
function nextApiKeyPage() {
  if (currentApiKeyPage < totalApiKeyPages) {
    goToApiKeyPage(currentApiKeyPage + 1);
  }
}

/**
 * Handles the bulk deletion of API keys based on input from the modal.
 */
function handleBulkDeleteApiKeys() {
  if (!bulkDeleteApiKeyInput || !bulkDeleteApiKeyModal) return;

  const bulkText = bulkDeleteApiKeyInput.value;
  if (!bulkText.trim()) {
    showNotification("请粘贴需要删除的 API 密钥", "warning");
    return;
  }

  const keysToDelete = new Set(bulkText.match(API_KEY_REGEX) || []);

  if (keysToDelete.size === 0) {
    showNotification("未在输入内容中提取到有效的 API 密钥格式", "warning");
    return;
  }

  // 从allApiKeys数组中删除匹配的密钥
  let deleteCount = 0;
  allApiKeys = allApiKeys.filter(key => {
    if (keysToDelete.has(key)) {
      deleteCount++;
      return false;
    }
    return true;
  });

  // 更新过滤后的数组
  const searchTerm = apiKeySearchInput ? apiKeySearchInput.value.toLowerCase() : "";
  if (!searchTerm) {
    filteredApiKeys = [...allApiKeys];
  } else {
    filteredApiKeys = allApiKeys.filter(key =>
      key.toLowerCase().includes(searchTerm)
    );
  }

  // 重新渲染当前页
  renderApiKeyPage();
  updateApiKeyPagination();

  closeModal(bulkDeleteApiKeyModal);

  if (deleteCount > 0) {
    showNotification(`成功删除了 ${deleteCount} 个匹配的密钥`, "success");
  } else {
    showNotification("列表中未找到您输入的任何密钥进行删除", "info");
  }
  bulkDeleteApiKeyInput.value = "";
}

/**
 * Handles the bulk addition of proxies from the modal input.
 */
function handleBulkAddProxies() {
  const proxyContainer = document.getElementById("PROXIES_container");
  if (!proxyBulkInput || !proxyContainer || !proxyModal) return;

  const bulkText = proxyBulkInput.value;
  const extractedProxies = bulkText.match(PROXY_REGEX) || [];

  const currentProxyInputs = proxyContainer.querySelectorAll(
    `.${ARRAY_INPUT_CLASS}`
  );
  const currentProxies = Array.from(currentProxyInputs)
    .map((input) => input.value)
    .filter((proxy) => proxy.trim() !== "");

  const combinedProxies = new Set([...currentProxies, ...extractedProxies]);
  const uniqueProxies = Array.from(combinedProxies);

  proxyContainer.innerHTML = ""; // Clear existing items

  uniqueProxies.forEach((proxy) => {
    addArrayItemWithValue("PROXIES", proxy);
  });

  closeModal(proxyModal);
  showNotification(`添加/更新了 ${uniqueProxies.length} 个唯一代理`, "success");
}

/**
 * Handles the bulk deletion of proxies based on input from the modal.
 */
function handleBulkDeleteProxies() {
  const proxyContainer = document.getElementById("PROXIES_container");
  if (!bulkDeleteProxyInput || !proxyContainer || !bulkDeleteProxyModal) return;

  const bulkText = bulkDeleteProxyInput.value;
  if (!bulkText.trim()) {
    showNotification("请粘贴需要删除的代理地址", "warning");
    return;
  }

  const proxiesToDelete = new Set(bulkText.match(PROXY_REGEX) || []);

  if (proxiesToDelete.size === 0) {
    showNotification("未在输入内容中提取到有效的代理地址格式", "warning");
    return;
  }

  const proxyItems = proxyContainer.querySelectorAll(`.${ARRAY_ITEM_CLASS}`);
  let deleteCount = 0;

  proxyItems.forEach((item) => {
    const input = item.querySelector(`.${ARRAY_INPUT_CLASS}`);
    if (input && proxiesToDelete.has(input.value)) {
      item.remove();
      deleteCount++;
    }
  });

  closeModal(bulkDeleteProxyModal);

  if (deleteCount > 0) {
    showNotification(`成功删除了 ${deleteCount} 个匹配的代理`, "success");
  } else {
    showNotification("列表中未找到您输入的任何代理进行删除", "info");
  }
  bulkDeleteProxyInput.value = "";
}

/**
 * Handles the bulk addition of Vertex Express API keys from the modal input.
 */
function handleBulkAddVertexApiKeys() {
  const vertexApiKeyContainer = document.getElementById(
    "VERTEX_API_KEYS_container"
  );
  if (!vertexApiKeyBulkInput || !vertexApiKeyContainer || !vertexApiKeyModal) {
    return;
  }

  const bulkText = vertexApiKeyBulkInput.value;
  const extractedKeys = bulkText.match(VERTEX_API_KEY_REGEX) || [];

  const currentKeyInputs = vertexApiKeyContainer.querySelectorAll(
    `.${ARRAY_INPUT_CLASS}.${SENSITIVE_INPUT_CLASS}`
  );
  let currentKeys = Array.from(currentKeyInputs)
    .map((input) => {
      return input.hasAttribute("data-real-value")
        ? input.getAttribute("data-real-value")
        : input.value;
    })
    .filter((key) => key && key.trim() !== "" && key !== MASKED_VALUE);

  const combinedKeys = new Set([...currentKeys, ...extractedKeys]);
  const uniqueKeys = Array.from(combinedKeys);

  vertexApiKeyContainer.innerHTML = ""; // Clear existing items

  uniqueKeys.forEach((key) => {
    addArrayItemWithValue("VERTEX_API_KEYS", key); // VERTEX_API_KEYS are sensitive
  });

  // Ensure new sensitive inputs are masked
  const newKeyInputs = vertexApiKeyContainer.querySelectorAll(
    `.${ARRAY_INPUT_CLASS}.${SENSITIVE_INPUT_CLASS}`
  );
  newKeyInputs.forEach((input) => {
    if (configForm && typeof initializeSensitiveFields === "function") {
      const focusoutEvent = new Event("focusout", {
        bubbles: true,
        cancelable: true,
      });
      input.dispatchEvent(focusoutEvent);
    }
  });

  closeModal(vertexApiKeyModal);
  showNotification(
    `添加/更新了 ${uniqueKeys.length} 个唯一 Vertex 密钥`,
    "success"
  );
  vertexApiKeyBulkInput.value = "";
}

/**
 * Handles the bulk deletion of Vertex Express API keys based on input from the modal.
 */
function handleBulkDeleteVertexApiKeys() {
  const vertexApiKeyContainer = document.getElementById(
    "VERTEX_API_KEYS_container"
  );
  if (
    !bulkDeleteVertexApiKeyInput ||
    !vertexApiKeyContainer ||
    !bulkDeleteVertexApiKeyModal
  ) {
    return;
  }

  const bulkText = bulkDeleteVertexApiKeyInput.value;
  if (!bulkText.trim()) {
    showNotification("请粘贴需要删除的 Vertex Express API 密钥", "warning");
    return;
  }

  const keysToDelete = new Set(bulkText.match(VERTEX_API_KEY_REGEX) || []);

  if (keysToDelete.size === 0) {
    showNotification(
      "未在输入内容中提取到有效的 Vertex Express API 密钥格式",
      "warning"
    );
    return;
  }

  const keyItems = vertexApiKeyContainer.querySelectorAll(
    `.${ARRAY_ITEM_CLASS}`
  );
  let deleteCount = 0;

  keyItems.forEach((item) => {
    const input = item.querySelector(
      `.${ARRAY_INPUT_CLASS}.${SENSITIVE_INPUT_CLASS}`
    );
    const realValue =
      input &&
      (input.hasAttribute("data-real-value")
        ? input.getAttribute("data-real-value")
        : input.value);
    if (realValue && keysToDelete.has(realValue)) {
      item.remove();
      deleteCount++;
    }
  });

  closeModal(bulkDeleteVertexApiKeyModal);

  if (deleteCount > 0) {
    showNotification(
      `成功删除了 ${deleteCount} 个匹配的 Vertex 密钥`,
      "success"
    );
  } else {
    showNotification("列表中未找到您输入的任何 Vertex 密钥进行删除", "info");
  }
  bulkDeleteVertexApiKeyInput.value = "";
}

/**
 * Switches the active configuration tab.
 * @param {string} tabId - The ID of the tab to switch to.
 */
function switchTab(tabId) {
  console.log(`Switching to tab: ${tabId}`);

  // 定义选中态和未选中态的样式
  const activeStyle =
    "background-color: #3b82f6 !important; color: #ffffff !important; border: 2px solid #2563eb !important; box-shadow: 0 4px 12px -2px rgba(59, 130, 246, 0.4), 0 2px 6px -1px rgba(59, 130, 246, 0.2) !important; transform: translateY(-2px) !important; font-weight: 600 !important;";
  const inactiveStyle =
    "background-color: #f8fafc !important; color: #64748b !important; border: 2px solid #e2e8f0 !important; box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1) !important; font-weight: 500 !important; transform: none !important;";

  // 更新标签按钮状态
  const tabButtons = document.querySelectorAll(".tab-btn");
  console.log(`Found ${tabButtons.length} tab buttons`);

  tabButtons.forEach((button) => {
    const buttonTabId = button.getAttribute("data-tab");
    if (buttonTabId === tabId) {
      // 激活状态：直接设置内联样式
      button.classList.add("active");
      button.setAttribute("style", activeStyle);
      console.log(`Applied active style to button: ${buttonTabId}`);
    } else {
      // 非激活状态：直接设置内联样式
      button.classList.remove("active");
      button.setAttribute("style", inactiveStyle);
      console.log(`Applied inactive style to button: ${buttonTabId}`);
    }
  });

  // 更新内容区域
  const sections = document.querySelectorAll(".config-section");
  sections.forEach((section) => {
    if (section.id === `${tabId}-section`) {
      section.classList.add("active");
    } else {
      section.classList.remove("active");
    }
  });
}

/**
 * Toggles the visibility of configuration sections for different upload providers.
 * @param {string} provider - The selected upload provider.
 */
function toggleProviderConfig(provider) {
  const providerConfigs = document.querySelectorAll(".provider-config");
  providerConfigs.forEach((config) => {
    if (config.getAttribute("data-provider") === provider) {
      config.classList.add("active");
    } else {
      config.classList.remove("active");
    }
  });
}

/**
 * Creates and appends an input field for an array item.
 * @param {string} key - The configuration key for the array.
 * @param {string} value - The initial value for the input field.
 * @param {boolean} isSensitive - Whether the input is for sensitive data.
 * @param {string|null} modelId - Optional model ID for thinking models.
 * @returns {HTMLInputElement} The created input element.
 */
function createArrayInput(key, value, isSensitive, modelId = null) {
  const input = document.createElement("input");
  input.type = "text";
  input.name = `${key}[]`; // Used for form submission if not handled by JS
  input.value = value;
  let inputClasses = `${ARRAY_INPUT_CLASS} flex-grow px-3 py-2 border-none rounded-l-md focus:outline-none form-input-themed`;
  if (isSensitive) {
    inputClasses += ` ${SENSITIVE_INPUT_CLASS}`;
  }
  input.className = inputClasses;
  if (modelId) {
    input.setAttribute("data-model-id", modelId);
    input.placeholder = "思考模型名称";
  }
  return input;
}

/**
 * Creates a generate token button for allowed tokens.
 * @returns {HTMLButtonElement} The created button element.
 */
function createGenerateTokenButton() {
  const generateBtn = document.createElement("button");
  generateBtn.type = "button";
  generateBtn.className =
    "generate-btn px-2 py-2 text-gray-500 hover:text-primary-600 focus:outline-none rounded-r-md bg-gray-100 hover:bg-gray-200 transition-colors";
  generateBtn.innerHTML = '<i class="fas fa-dice"></i>';
  generateBtn.title = "生成随机令牌";
  // Event listener will be added via delegation in DOMContentLoaded
  return generateBtn;
}

/**
 * Creates a remove button for an array item.
 * @returns {HTMLButtonElement} The created button element.
 */
function createRemoveButton() {
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className =
    "remove-btn text-gray-400 hover:text-red-500 focus:outline-none transition-colors duration-150";
  removeBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
  removeBtn.title = "删除";
  // Event listener will be added via delegation in DOMContentLoaded
  return removeBtn;
}

/**
 * Creates a proxy status icon for displaying proxy check status.
 * @returns {HTMLSpanElement} The status icon element.
 */
function createProxyStatusIcon() {
  const statusIcon = document.createElement("span");
  statusIcon.className = "proxy-status-icon px-2 py-2 text-gray-400";
  statusIcon.innerHTML = '<i class="fas fa-question-circle" title="未检测"></i>';
  statusIcon.setAttribute("data-status", "unknown");
  return statusIcon;
}

/**
 * Creates a proxy check button for individual proxy checking.
 * @returns {HTMLButtonElement} The check button element.
 */
function createProxyCheckButton() {
  const checkBtn = document.createElement("button");
  checkBtn.type = "button";
  checkBtn.className =
    "proxy-check-btn px-2 py-2 text-blue-500 hover:text-blue-700 focus:outline-none transition-colors duration-150 rounded-r-md";
  checkBtn.innerHTML = '<i class="fas fa-globe"></i>';
  checkBtn.title = "检测此代理";
  
  // 添加点击事件监听器
  checkBtn.addEventListener("click", function(e) {
    e.preventDefault();
    e.stopPropagation();
    const inputElement = this.closest('.flex').querySelector('.array-input');
    if (inputElement && inputElement.value.trim()) {
      checkSingleProxy(inputElement.value.trim(), this);
    } else {
      showNotification("请先输入代理地址", "warning");
    }
  });
  
  return checkBtn;
}

/**
 * Adds a new item to an array configuration section (e.g., API_KEYS, ALLOWED_TOKENS).
 * This function is typically called by a "+" button.
 * @param {string} key - The configuration key for the array (e.g., 'API_KEYS').
 */
function addArrayItem(key) {
  const container = document.getElementById(`${key}_container`);
  if (!container) return;

  const newItemValue = ""; // New items start empty
  const modelId = addArrayItemWithValue(key, newItemValue); // This adds the DOM element

  if (key === "THINKING_MODELS" && modelId) {
    createAndAppendBudgetMapItem(newItemValue, -1, modelId); // Default budget -1
  }
}

/**
 * Adds an array item with a specific value to the DOM.
 * This is used both for initially populating the form and for adding new items.
 * @param {string} key - The configuration key (e.g., 'API_KEYS', 'THINKING_MODELS').
 * @param {string} value - The value for the array item.
 * @returns {string|null} The generated modelId if it's a thinking model, otherwise null.
 */
function addArrayItemWithValue(key, value) {
  const container = document.getElementById(`${key}_container`);
  if (!container) return null;

  const isThinkingModel = key === "THINKING_MODELS";
  const isAllowedToken = key === "ALLOWED_TOKENS";
  const isVertexApiKey = key === "VERTEX_API_KEYS"; // 新增判断
  const isProxy = key === "PROXIES"; // 新增代理判断
  const isSensitive = key === "API_KEYS" || isAllowedToken || isVertexApiKey; // 更新敏感判断
  const modelId = isThinkingModel ? generateUUID() : null;

  const arrayItem = document.createElement("div");
  arrayItem.className = `${ARRAY_ITEM_CLASS} flex items-center mb-2 gap-2`;
  if (isThinkingModel) {
    arrayItem.setAttribute("data-model-id", modelId);
  }

  const inputWrapper = document.createElement("div");
  inputWrapper.className =
    "flex items-center flex-grow rounded-md focus-within:border-blue-500 focus-within:ring focus-within:ring-blue-500 focus-within:ring-opacity-50";
  // Apply light theme border directly via style
  inputWrapper.style.border = "1px solid rgba(0, 0, 0, 0.12)";
  inputWrapper.style.backgroundColor = "transparent"; // Ensure wrapper is transparent

  const input = createArrayInput(
    key,
    value,
    isSensitive,
    isThinkingModel ? modelId : null
  );
  inputWrapper.appendChild(input);

  if (isAllowedToken) {
    const generateBtn = createGenerateTokenButton();
    inputWrapper.appendChild(generateBtn);
  } else if (isProxy) {
    // 为代理添加状态显示和检测按钮
    const proxyStatusIcon = createProxyStatusIcon();
    inputWrapper.appendChild(proxyStatusIcon);
    
    const proxyCheckBtn = createProxyCheckButton();
    inputWrapper.appendChild(proxyCheckBtn);
  } else {
    // Ensure right-side rounding if no button is present
    input.classList.add("rounded-r-md");
  }

  const removeBtn = createRemoveButton();

  arrayItem.appendChild(inputWrapper);
  arrayItem.appendChild(removeBtn);
  container.appendChild(arrayItem);

  // Initialize sensitive field if applicable
  if (isSensitive && input.value) {
    if (configForm && typeof initializeSensitiveFields === "function") {
      const focusoutEvent = new Event("focusout", {
        bubbles: true,
        cancelable: true,
      });
      input.dispatchEvent(focusoutEvent);
    }
  }
  return isThinkingModel ? modelId : null;
}

/**
 * Creates and appends a DOM element for a thinking model's budget mapping.
 * @param {string} mapKey - The model name (key for the map).
 * @param {number|string} mapValue - The budget value.
 * @param {string} modelId - The unique ID of the corresponding thinking model.
 */
function createAndAppendBudgetMapItem(mapKey, mapValue, modelId) {
  const container = document.getElementById("THINKING_BUDGET_MAP_container");
  if (!container) {
    console.error(
      "Cannot add budget item: THINKING_BUDGET_MAP_container not found!"
    );
    return;
  }

  // If container currently only has the placeholder, clear it
  const placeholder = container.querySelector(".text-gray-500.italic");
  // Check if the only child is the placeholder before clearing
  if (
    placeholder &&
    container.children.length === 1 &&
    container.firstChild === placeholder
  ) {
    container.innerHTML = "";
  }

  const mapItem = document.createElement("div");
  mapItem.className = `${MAP_ITEM_CLASS} flex items-center mb-2 gap-2`;
  mapItem.setAttribute("data-model-id", modelId);

  const keyInput = document.createElement("input");
  keyInput.type = "text";
  keyInput.value = mapKey;
  keyInput.placeholder = "模型名称 (自动关联)";
  keyInput.readOnly = true;
  keyInput.className = `${MAP_KEY_INPUT_CLASS} flex-grow px-3 py-2 border border-gray-300 rounded-md focus:outline-none bg-gray-100 text-gray-500`;
  keyInput.setAttribute("data-model-id", modelId);

  const valueInput = document.createElement("input");
  valueInput.type = "number";
  const intValue = parseInt(mapValue, 10);
  valueInput.value = isNaN(intValue) ? -1 : intValue;
  valueInput.placeholder = "预算 (整数)";
  valueInput.className = `${MAP_VALUE_INPUT_CLASS} w-24 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:border-primary-500 focus:ring focus:ring-primary-200 focus:ring-opacity-50`;
  valueInput.min = -1;
  valueInput.max = 32767;
  valueInput.addEventListener("input", function () {
    let val = this.value.replace(/[^0-9-]/g, "");
    if (val !== "") {
      val = parseInt(val, 10);
      if (val < -1) val = -1;
      if (val > 32767) val = 32767;
    }
    this.value = val; // Corrected variable name
  });

  // Remove Button - Removed for budget map items
  // const removeBtn = document.createElement('button');
  // removeBtn.type = 'button';
  // removeBtn.className = 'remove-btn text-gray-300 cursor-not-allowed focus:outline-none'; // Kept original class for reference
  // removeBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
  // removeBtn.title = '请从上方模型列表删除';
  // removeBtn.disabled = true;

  mapItem.appendChild(keyInput);
  mapItem.appendChild(valueInput);
  // mapItem.appendChild(removeBtn); // Do not append the remove button

  container.appendChild(mapItem);
}

/**
 * Adds a new custom header item to the DOM.
 */
function addCustomHeaderItem() {
  createAndAppendCustomHeaderItem("", "");
}

/**
 * Creates and appends a DOM element for a custom header.
 * @param {string} key - The header key.
 * @param {string} value - The header value.
 */
function createAndAppendCustomHeaderItem(key, value) {
  const container = document.getElementById("CUSTOM_HEADERS_container");
  if (!container) {
    console.error(
      "Cannot add custom header: CUSTOM_HEADERS_container not found!"
    );
    return;
  }

  const placeholder = container.querySelector(".text-gray-500.italic");
  if (
    placeholder &&
    container.children.length === 1 &&
    container.firstChild === placeholder
  ) {
    container.innerHTML = "";
  }

  const headerItem = document.createElement("div");
  headerItem.className = `${CUSTOM_HEADER_ITEM_CLASS} flex items-center mb-2 gap-2`;

  const keyInput = document.createElement("input");
  keyInput.type = "text";
  keyInput.value = key;
  keyInput.placeholder = "Header Name";
  keyInput.className = `${CUSTOM_HEADER_KEY_INPUT_CLASS} flex-grow px-3 py-2 border border-gray-300 rounded-md focus:outline-none bg-gray-100 text-gray-500`;

  const valueInput = document.createElement("input");
  valueInput.type = "text";
  valueInput.value = value;
  valueInput.placeholder = "Header Value";
  valueInput.className = `${CUSTOM_HEADER_VALUE_INPUT_CLASS} flex-grow px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:border-primary-500 focus:ring focus:ring-primary-200 focus:ring-opacity-50`;

  const removeBtn = createRemoveButton();
  removeBtn.addEventListener("click", () => {
    headerItem.remove();
    if (container.children.length === 0) {
      container.innerHTML =
        '<div class="text-gray-500 text-sm italic">添加自定义请求头，例如 X-Api-Key: your-key</div>';
    }
  });

  headerItem.appendChild(keyInput);
  headerItem.appendChild(valueInput);
  headerItem.appendChild(removeBtn);

  container.appendChild(headerItem);
}

/**
 * Collects all data from the configuration form.
 * @returns {object} An object containing all configuration data.
 */
function collectFormData() {
    const formData = {};
    const form = document.getElementById('configForm');

    // Handle standard inputs, selects, textareas
    form.querySelectorAll('input, select, textarea').forEach(el => {
        if (!el.name || el.closest(`.${ARRAY_ITEM_CLASS}`)) return;

        if (el.type === 'checkbox') {
            formData[el.name] = el.checked;
        } else if (el.type === 'number') {
            formData[el.name] = parseFloat(el.value) || 0;
        } else if (el.classList.contains(SENSITIVE_INPUT_CLASS) && el.hasAttribute('data-real-value')) {
            formData[el.name] = el.getAttribute('data-real-value');
        } else {
            formData[el.name] = el.value;
        }
    });

    // Handle API_KEYS from global array
    formData['API_KEYS'] = allApiKeys;

    // Handle ALLOWED_TOKENS
    const allowedTokensContainer = document.getElementById("ALLOWED_TOKENS_container");
    if(allowedTokensContainer) {
        formData['ALLOWED_TOKENS'] = Array.from(allowedTokensContainer.querySelectorAll(`.${ARRAY_INPUT_CLASS}`))
            .map(input => input.classList.contains(SENSITIVE_INPUT_CLASS) && input.hasAttribute('data-real-value') ? input.getAttribute('data-real-value') : input.value)
            .filter(value => value && value.trim() !== "");
    }

    // Handle CUSTOM_HEADERS
  const customHeadersContainer = document.getElementById(
    "CUSTOM_HEADERS_container"
  );
    if(customHeadersContainer) {
        formData['CUSTOM_HEADERS'] = {};
        customHeadersContainer.querySelectorAll(`.${CUSTOM_HEADER_ITEM_CLASS}`).forEach(item => {
            const keyInput = item.querySelector(`.${CUSTOM_HEADER_KEY_INPUT_CLASS}`);
            const valueInput = item.querySelector(`.${CUSTOM_HEADER_VALUE_INPUT_CLASS}`);
            if (keyInput && valueInput && keyInput.value.trim() !== "") {
                formData['CUSTOM_HEADERS'][keyInput.value.trim()] = valueInput.value.trim();
            }
        });
    }
    
    return formData;
}

/**
 * Stops the scheduler task on the server.
 */
async function stopScheduler() {
  try {
    const response = await fetch("/api/scheduler/stop", { method: "POST" });
    if (!response.ok) {
      console.warn(`停止定时任务失败: ${response.status}`);
    } else {
      console.log("定时任务已停止");
    }
  } catch (error) {
    console.error("调用停止定时任务API时出错:", error);
  }
}

/**
 * Starts the scheduler task on the server.
 */
async function startScheduler() {
  try {
    const response = await fetch("/api/scheduler/start", { method: "POST" });
    if (!response.ok) {
      console.warn(`启动定时任务失败: ${response.status}`);
    } else {
      console.log("定时任务已启动");
    }
  } catch (error) {
    console.error("调用启动定时任务API时出错:", error);
  }
}

/**
 * Saves the current configuration to the server.
 */
async function saveConfig() {
  try {
    const formData = collectFormData();

    showNotification("正在保存配置...", "info");

    // 1. 停止定时任务
    await stopScheduler();

    const response = await fetch("/api/config", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(formData),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(
        errorData.detail || `HTTP error! status: ${response.status}`
      );
    }

    const result = await response.json();

    // 移除居中的 saveStatus 提示

    showNotification("配置保存成功", "success");

    // 3. 启动新的定时任务
    await startScheduler();
  } catch (error) {
    console.error("保存配置失败:", error);
    // 保存失败时，也尝试重启定时任务，以防万一
    await startScheduler();
    // 移除居中的 saveStatus 提示

    showNotification("保存配置失败: " + error.message, "error");
  }
}

/**
 * Initiates the configuration reset process by showing a confirmation modal.
 * @param {Event} [event] - The click event, if triggered by a button.
 */
function resetConfig(event) {
  // 阻止事件冒泡和默认行为
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }

  console.log(
    "resetConfig called. Event target:",
    event ? event.target.id : "No event"
  );

  // Ensure modal is shown only if the event comes from the reset button
  if (
    !event ||
    event.target.id === "resetBtn" ||
    (event.currentTarget && event.currentTarget.id === "resetBtn")
  ) {
    if (resetConfirmModal) {
      openModal(resetConfirmModal);
    } else {
      console.error(
        "Reset confirmation modal not found! Falling back to default confirm."
      );
      if (confirm("确定要重置所有配置吗？这将恢复到默认值。")) {
        executeReset();
      }
    }
  }
}

/**
 * Executes the actual configuration reset after confirmation.
 */
async function executeReset() {
  try {
    showNotification("正在重置配置...", "info");

    // 1. 停止定时任务
    await stopScheduler();
    const response = await fetch("/api/config/reset", { method: "POST" });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const config = await response.json();
    populateForm(config);
    // Re-initialize masking for sensitive fields after reset
    initializeSensitiveFields();

    showNotification("配置已重置为默认值", "success");

    // 3. Start new scheduler task
    await startScheduler();
  } catch (error) {
    console.error("重置配置失败:", error);
    showNotification("重置配置失败: " + error.message, "error");
    await startScheduler();
  }
}

/**
 * Displays a notification message to the user.
 * @param {string} message - The message to display.
 * @param {string} [type='info'] - The type of notification ('info', 'success', 'error', 'warning').
 */
function showNotification(message, type = "info") {
  const notification = document.getElementById("notification");
  notification.textContent = message;

  notification.classList.remove("bg-danger-500");
  notification.classList.add("bg-black");
  notification.style.backgroundColor = "rgba(0,0,0,0.8)";
  notification.style.color = "#fff";

  notification.style.opacity = "1";
  notification.style.transform = "translate(-50%, 0)";

  setTimeout(() => {
    notification.style.opacity = "0";
    notification.style.transform = "translate(-50%, 10px)";
  }, 3000);
}

/**
 * Refreshes the current page.
 * Scrolls the page to the top.
 */
function scrollToTop() {
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/**
 * Scrolls the page to the bottom.
 */
function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

/**
 * Toggles the visibility of scroll-to-top/bottom buttons based on scroll position.
 */
function toggleScrollButtons() {
  const scrollButtons = document.querySelector(".scroll-buttons");
  if (scrollButtons) {
    scrollButtons.style.display = window.scrollY > 200 ? "flex" : "none";
  }
}

/**
 * Generates a random token string.
 * @returns {string} A randomly generated token.
 */
function generateRandomToken() {
  const characters =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_";
  const length = 48;
  let result = "sk-";
  for (let i = 0; i < length; i++) {
    result += characters.charAt(Math.floor(Math.random() * characters.length));
  }
  return result;
}

// --- Model Helper Functions ---
async function fetchModels() {
  if (cachedModelsList) {
    return cachedModelsList;
  }
  try {
    showNotification("正在从 /api/config/ui/models 加载模型列表...", "info");
    const response = await fetch("/api/config/ui/models");
    if (!response.ok) {
      const errorData = await response.text();
      throw new Error(`HTTP error ${response.status}: ${errorData}`);
    }
    const responseData = await response.json();
    if (responseData && Array.isArray(responseData.models)) {
      cachedModelsList = responseData.models.map(m => ({ id: m.name.replace('models/', '') }));
      showNotification("模型列表加载成功", "success");
      return cachedModelsList;
    } else {
      console.error("Invalid model list format received:", responseData);
      throw new Error("模型列表格式无效或请求未成功");
    }
  } catch (error) {
    console.error("加载模型列表失败:", error);
    showNotification(`加载模型列表失败: ${error.message}`, "error");
    cachedModelsList = []; // Avoid repeated fetches on error for this session, or set to null to retry
    return [];
  }
}

function renderModelsInModal() {
  if (!modelHelperListContainer) return;
  if (!cachedModelsList) {
    modelHelperListContainer.innerHTML =
      '<p class="text-gray-400 text-sm italic">模型列表尚未加载。</p>';
    return;
  }

  const searchTerm = modelHelperSearchInput.value.toLowerCase();
  const filteredModels = cachedModelsList.filter((model) =>
    model.id.toLowerCase().includes(searchTerm)
  );

  modelHelperListContainer.innerHTML = ""; // Clear previous items

  if (filteredModels.length === 0) {
    modelHelperListContainer.innerHTML =
      '<p class="text-gray-400 text-sm italic">未找到匹配的模型。</p>';
    return;
  }

  filteredModels.forEach((model) => {
    const modelItemElement = document.createElement("button");
    modelItemElement.type = "button";
    modelItemElement.textContent = model.id;
    modelItemElement.className =
      "block w-full text-left px-4 py-2 rounded-md hover:bg-blue-100 focus:bg-blue-100 focus:outline-none transition-colors text-gray-700 hover:text-gray-800";

    modelItemElement.addEventListener("click", () =>
      handleModelSelection(model.id)
    );
    modelHelperListContainer.appendChild(modelItemElement);
  });
}

async function openModelHelperModal() {
  if (!currentModelHelperTarget) {
    console.error("Model helper target not set.");
    showNotification("无法打开模型助手：目标未设置", "error");
    return;
  }

  await fetchModels(); // Ensure models are loaded
  renderModelsInModal(); // Render them (handles empty/error cases internally)

  if (modelHelperTitleElement) {
    if (currentModelHelperTarget.type === "input" && currentModelHelperTarget.target) {
      const label = document.querySelector(`label[for="${currentModelHelperTarget.target.id}"]`);
      modelHelperTitleElement.textContent = label ? `Select model for "${label.textContent.trim()}"` : "Select Model";
    } else {
      modelHelperTitleElement.textContent = "Select Model";
    }
  }
  if (modelHelperSearchInput) modelHelperSearchInput.value = "";
  if (modelHelperModal) openModal(modelHelperModal);
}

function handleModelSelection(selectedModelId) {
  if (!currentModelHelperTarget) return;

  if (
    currentModelHelperTarget.type === "input" && currentModelHelperTarget.target
  ) {
    const inputElement = currentModelHelperTarget.target;
    inputElement.value = selectedModelId;
    if (inputElement.classList.contains(SENSITIVE_INPUT_CLASS)) {
      inputElement.dispatchEvent(new Event("focusout", { bubbles: true, cancelable: true }));
    }
    inputElement.dispatchEvent(new Event("input", { bubbles: true }));
  }

  if (modelHelperModal) closeModal(modelHelperModal);
  currentModelHelperTarget = null;
}

// -- End Model Helper Functions --