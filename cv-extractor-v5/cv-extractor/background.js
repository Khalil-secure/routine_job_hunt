'use strict';

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch(console.error);

// Relay: side panel asks background to get the real active tab
// (background holds the activeTab grant; the panel context does not)
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === 'getActiveTab') {
    chrome.tabs.query({ active: true, lastFocusedWindow: true }, (tabs) => {
      const tab = (tabs || []).find(t => t.url && t.url.startsWith('http')) || tabs?.[0];
      sendResponse(tab ? { tabId: tab.id, url: tab.url } : { error: 'No active tab' });
    });
    return true; // keep channel open for async sendResponse
  }

  if (msg.action === 'injectAndQuery') {
    const { tabId } = msg;
    chrome.scripting.executeScript(
      { target: { tabId }, files: ['content.js'] },
      () => {
        const err = chrome.runtime.lastError;
        sendResponse({ ok: !err, error: err?.message });
      }
    );
    return true;
  }
});
