(function () {
  "use strict";

  var money = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
  var quantityFormat = new Intl.NumberFormat("ru-RU");

  function ready(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback);
    } else {
      callback();
    }
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setText(target, text) {
    var node = typeof target === "string" ? byId(target) : target;
    if (node) {
      node.textContent = text;
    }
  }

  function csrfToken() {
    var input = document.querySelector("input[name='csrfmiddlewaretoken']");
    if (input) {
      return input.value;
    }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function showFlash(message, variant) {
    var area = byId("flash-area");
    if (!area) {
      window.alert(message);
      return;
    }
    var alert = document.createElement("div");
    alert.className = "alert alert-" + (variant || "success") + " alert-dismissible fade show";
    alert.setAttribute("role", "status");
    alert.textContent = message;

    var close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close";
    close.setAttribute("aria-label", "Закрыть");
    close.addEventListener("click", function () {
      alert.remove();
    });
    alert.appendChild(close);

    area.appendChild(alert);
    window.setTimeout(function () {
      if (alert.isConnected) {
        alert.remove();
      }
    }, 5000);
  }

  function clearErrors(form) {
    form.querySelectorAll("[data-field-error], [data-form-error]").forEach(function (node) {
      node.textContent = "";
    });
  }

  function fieldErrorNode(form, field) {
    return form.querySelector('[data-field-error="' + field + '"]');
  }

  function setFieldError(form, field, message) {
    var node = fieldErrorNode(form, field);
    if (node) {
      node.textContent = message;
      return true;
    }
    return false;
  }

  function setFormError(form, message) {
    var node = form.querySelector("[data-form-error]");
    if (node) {
      node.textContent = message;
    } else {
      showFlash(message, "danger");
    }
  }

  function setBusy(form, busy) {
    var submit = form.querySelector("button[type='submit']");
    if (busy) {
      form.dataset.busy = "1";
      if (submit) {
        submit.dataset.originalText = submit.textContent;
        submit.textContent = "Подождите…";
        submit.disabled = true;
      }
    } else {
      delete form.dataset.busy;
      if (submit) {
        if (submit.dataset.originalText) {
          submit.textContent = submit.dataset.originalText;
          delete submit.dataset.originalText;
        }
        submit.disabled = false;
      }
    }
  }

  async function postForm(url, form) {
    var response = await fetch(url, {
      method: "POST",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken(),
        Accept: "application/json"
      },
      body: new FormData(form),
      credentials: "same-origin"
    });

    var payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }

    if (!payload) {
      throw new Error(
        "Сервер вернул неожиданный ответ (возможно, устарел кеш JS). " +
          "Обновите страницу через Ctrl+F5 и попробуйте снова."
      );
    }
    if (!response.ok || payload.ok === false) {
      var failure = new Error(payload.error || "Не удалось выполнить операцию.");
      failure.payload = payload;
      throw failure;
    }
    return payload;
  }

  function hideModal(element) {
    if (element && window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(element).hide();
    }
  }

  function applySummary(summary) {
    if (!summary) {
      return;
    }
    setText("stat-count", quantityFormat.format(summary.count));
    setText("stat-units", quantityFormat.format(summary.units));
    setText("stat-value", money.format(summary.value));
  }

  function applyProduct(product) {
    var row = document.querySelector('tr[data-product-id="' + product.id + '"]');
    if (!row) {
      return;
    }

    setText(row.querySelector(".product-name"), product.name);
    setText(row.querySelector(".price-value"), money.format(product.price));
    setText(row.querySelector(".purchase-value"), money.format(product.purchase_price));
    setText(row.querySelector(".qty-value"), quantityFormat.format(product.quantity));

    row.classList.remove("row-ok", "row-low", "row-out");
    row.classList.add("row-" + product.status);

    var badge = row.querySelector(".badge");
    if (badge) {
      badge.className = "badge badge-" + product.status;
      badge.textContent = product.status_label;
    }

    var soldOut = product.quantity === 0;
    var sellButton = row.querySelector('[data-bs-target="#sellModal"]');
    if (sellButton) {
      sellButton.classList.toggle("btn-sell--out", soldOut);
      sellButton.title = soldOut
        ? "Товар закончился — сначала оформите приход"
        : "Продать";
      sellButton.setAttribute("data-product-name", product.name);
      sellButton.setAttribute("data-product-qty", String(product.quantity));
      sellButton.setAttribute("data-product-price", String(product.price));
    }

    var editButton = row.querySelector('[data-bs-target="#editModal"]');
    if (editButton) {
      editButton.setAttribute("data-product-name", product.name);
      editButton.setAttribute("data-product-price", String(product.price));
      editButton.setAttribute("data-product-purchase", String(product.purchase_price));
    }

    var deleteButton = row.querySelector('[data-bs-target="#deleteModal"]');
    if (deleteButton) {
      deleteButton.setAttribute("data-product-name", product.name);
    }
  }

  function ensureEmptyState() {
    var tbody = byId("products-tbody");
    if (!tbody) {
      return;
    }
    var rows = tbody.querySelectorAll("tr[data-product-id]");
    var emptyRow = tbody.querySelector(".empty-row");

    if (rows.length === 0 && !emptyRow) {
      var row = document.createElement("tr");
      row.className = "empty-row";
      var cell = document.createElement("td");
      cell.colSpan = document.querySelectorAll(".products-table thead th").length;
      cell.className = "text-center text-muted py-5";
      cell.textContent = tbody.getAttribute("data-empty-message") || "Товаров пока нет.";
      row.appendChild(cell);
      tbody.appendChild(row);
    } else if (rows.length > 0 && emptyRow) {
      emptyRow.remove();
    }
  }

  function openSellModal(button) {
    var form = byId("sell-form");
    if (!form) {
      return;
    }
    var quantity = parseInt(button.getAttribute("data-product-qty"), 10) || 0;
    var price = button.getAttribute("data-product-price") || "0";
    var name = button.getAttribute("data-product-name") || "";

    form.dataset.url = button.getAttribute("data-sell-url") || "";
    form.dataset.stock = String(quantity);
    form.action = form.dataset.url || "";

    setText(
      "sell-product-info",
      name + " · в наличии " + quantityFormat.format(quantity) + " шт · " +
        money.format(price) + " ₽"
    );

    var input = byId("sell-quantity");
    var submit = form.querySelector("button[type='submit']");
    var warning = byId("sell-stock-warning");
    var soldOut = quantity === 0;

    if (input) {
      input.max = String(Math.max(1, quantity));
      input.value = "1";
      input.disabled = soldOut;
    }
    if (submit) {
      submit.disabled = soldOut;
    }
    if (warning) {
      warning.classList.toggle("d-none", !soldOut);
    }

    var cash = form.querySelector('input[name="payment_method"][value="cash"]');
    if (cash) {
      cash.checked = true;
    }
    clearErrors(form);
  }

  function openEditModal(button) {
    var form = byId("edit-form");
    if (!form) {
      return;
    }
    form.dataset.url = button.getAttribute("data-edit-url") || "";
    form.action = form.dataset.url || "";

    byId("edit-name").value = button.getAttribute("data-product-name") || "";
    byId("edit-price").value = button.getAttribute("data-product-price") || "";
    byId("edit-purchase").value = button.getAttribute("data-product-purchase") || "";
    clearErrors(form);
  }

  function openDeleteModal(button) {
    var form = byId("delete-form");
    if (!form) {
      return;
    }
    form.dataset.url = button.getAttribute("data-delete-url") || "";
    form.action = form.dataset.url || "";
    setText("delete-product-name", button.getAttribute("data-product-name") || "");
    clearErrors(form);
  }

  async function perform(form, onSuccess, errorField) {
    var url = form.dataset.url || form.getAttribute("action") || "";
    if (!url || url === "#") {
      setFormError(form, "Не удалось определить адрес операции. Обновите страницу.");
      return;
    }

    setBusy(form, true);
    try {
      var data = await postForm(url, form);
      onSuccess(data);
    } catch (error) {
      var payload = error.payload || {};
      var errors = payload.errors || {};
      var shown = false;
      Object.keys(errors).forEach(function (field) {
        if (setFieldError(form, field, errors[field])) {
          shown = true;
        }
      });
      if (!shown) {
        if (errorField && setFieldError(form, errorField, error.message)) {
          shown = true;
        }
      }
      if (!shown) {
        setFormError(form, error.message);
      }
    } finally {
      setBusy(form, false);
    }
  }

  function submitSell(form) {
    clearErrors(form);

    var input = byId("sell-quantity");
    var quantity = Number(input.value);
    var stock = Number(form.dataset.stock || 0);

    if (!Number.isInteger(quantity) || quantity < 1) {
      setFieldError(form, "quantity", "Введите целое количество больше нуля.");
      input.focus();
      return;
    }
    if (quantity > stock) {
      setFieldError(
        form,
        "quantity",
        "Недостаточно товара на складе: в наличии " +
          quantityFormat.format(stock) + " шт."
      );
      input.focus();
      return;
    }

    perform(
      form,
      function (data) {
        applyProduct(data.product);
        applySummary(data.summary);
        hideModal(byId("sellModal"));
        showFlash(data.message, "success");
      },
      "quantity"
    );
  }

  function submitEdit(form) {
    clearErrors(form);

    var price = Number(byId("edit-price").value);
    var purchase = Number(byId("edit-purchase").value);
    if (
      Number.isFinite(price) &&
      Number.isFinite(purchase) &&
      purchase > price
    ) {
      setFieldError(
        form,
        "purchase_price",
        "Закупочная цена не может быть выше цены продажи."
      );
      byId("edit-purchase").focus();
      return;
    }

    perform(form, function (data) {
      applyProduct(data.product);
      applySummary(data.summary);
      hideModal(byId("editModal"));
      showFlash(data.message, "success");
    });
  }

  function submitDelete(form) {
    clearErrors(form);
    perform(form, function (data) {
      var row = document.querySelector('tr[data-product-id="' + data.deleted_id + '"]');
      if (row) {
        row.remove();
      }
      ensureEmptyState();
      applySummary(data.summary);
      hideModal(byId("deleteModal"));
      showFlash(data.message, "success");
    });
  }

  ready(function () {
    if (!window.fetch) {
      showFlash("Браузер не поддерживает fetch — обновите браузер.", "danger");
    }
    if (!window.bootstrap) {
      showFlash(
        "Не загрузился Bootstrap: модальные окна недоступны. " +
          "Обновите страницу через Ctrl+F5.",
        "danger"
      );
    }

    var modals = [
      ["sellModal", openSellModal],
      ["editModal", openEditModal],
      ["deleteModal", openDeleteModal]
    ];

    modals.forEach(function (pair) {
      var modal = byId(pair[0]);
      if (!modal) {
        return;
      }
      modal.addEventListener("show.bs.modal", function (event) {
        var button = event.relatedTarget;
        if (button) {
          pair[1](button);
        }
      });
    });

    var sellModalElement = byId("sellModal");
    if (sellModalElement) {
      sellModalElement.addEventListener("shown.bs.modal", function () {
        var input = byId("sell-quantity");
        if (input && !input.disabled) {
          input.focus();
          input.select();
        }
      });
    }

    var editModalElement = byId("editModal");
    if (editModalElement) {
      editModalElement.addEventListener("shown.bs.modal", function () {
        var input = byId("edit-name");
        if (input) {
          input.focus();
        }
      });
    }

    var handlers = {
      sell: submitSell,
      edit: submitEdit,
      delete: submitDelete
    };

    // Делегирование: работает даже если модалка перерисована/загружена позже.
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form || form.tagName !== "FORM") {
        return;
      }
      var action = form.getAttribute("data-ajax-form");
      if (!action || !handlers[action]) {
        return;
      }
      event.preventDefault();
      if (form.dataset.busy === "1") {
        return;
      }
      handlers[action](form);
    });

    /* --- Приход (обычная форма, перезагружает страницу) --- */
    var arrivalModal = byId("arrivalModal");
    if (arrivalModal) {
      arrivalModal.addEventListener("show.bs.modal", function (event) {
        var button = event.relatedTarget;
        if (!button) {
          return;
        }
        var quantity = parseInt(button.getAttribute("data-product-qty"), 10) || 0;

        byId("arrival-product-id").value = button.getAttribute("data-product-id") || "";
        setText(
          "arrival-product-name",
          (button.getAttribute("data-product-name") || "") +
            " · сейчас на складе " + quantityFormat.format(quantity) + " шт"
        );
        byId("arrival-quantity").value = "10";
      });

      arrivalModal.addEventListener("shown.bs.modal", function () {
        byId("arrival-quantity").focus();
      });
    }

    /* --- Списание (обычная форма, перезагружает страницу) --- */
    var writeoffModal = byId("writeoffModal");
    if (writeoffModal) {
      writeoffModal.addEventListener("show.bs.modal", function (event) {
        var button = event.relatedTarget;
        if (!button) {
          return;
        }
        var quantity = parseInt(button.getAttribute("data-product-qty"), 10) || 0;

        byId("writeoff-product-id").value = button.getAttribute("data-product-id") || "";
        setText(
          "writeoff-product-name",
          (button.getAttribute("data-product-name") || "") +
            " · на складе " + quantityFormat.format(quantity) + " шт"
        );
        byId("writeoff-quantity").value = "1";
        byId("writeoff-reason").value = "";
        var responsible = byId("writeoff-responsible");
        if (responsible) {
          responsible.value = "";
        }
      });

      writeoffModal.addEventListener("shown.bs.modal", function () {
        byId("writeoff-quantity").focus();
      });
    }
  });
})();
