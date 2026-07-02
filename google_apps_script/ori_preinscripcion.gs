const SHEET_NAME = 'Respuestas Ori';
const CONVERSATION_LOG_SHEET_NAME = 'Historial Ori';
const SPREADSHEET_ID = '1zfw1C4a0PxP1zZFJY4fD4C8x-5_ONDq1CPuwszVDXDo';

function doPost(e) {
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const expectedSecret = PropertiesService.getScriptProperties().getProperty('PREINSCRIPTION_WEBHOOK_SECRET') || '';
    if (expectedSecret && body.secret !== expectedSecret) {
      return jsonResponse({ ok: false, error: 'Secreto invalido' });
    }

    if (body.action === 'upload_file') {
      return jsonResponse(uploadFile(body));
    }
    if (body.action === 'submit_preinscription') {
      return jsonResponse(submitPreinscription(body));
    }
    if (body.action === 'update_confirmed_stand') {
      return jsonResponse(updateConfirmedStand(body));
    }
    if (body.action === 'delete_preinscription_by_chat_phone') {
      return jsonResponse(deletePreinscriptionByChatPhone(body));
    }
    if (body.action === 'append_conversation_log') {
      return jsonResponse(appendConversationLog(body));
    }

    return jsonResponse({ ok: false, error: 'Accion no reconocida' });
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error) });
  }
}

function doGet(e) {
  try {
    const params = (e && e.parameter) || {};
    const expectedSecret = PropertiesService.getScriptProperties().getProperty('PREINSCRIPTION_WEBHOOK_SECRET') || '';
    if (expectedSecret && params.secret !== expectedSecret) {
      return jsonResponse({ ok: false, error: 'Secreto invalido' });
    }

    if (params.action === 'list_preinscriptions') {
      return jsonResponse(listPreinscriptions());
    }

    return jsonResponse({ ok: true, service: 'Ori preinscripciones' });
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error) });
  }
}

function submitPreinscription(body) {
  const data = body.data || {};
  const sheet = getSheet();
  ensureHeaders(sheet);

  sheet.appendRow([
    body.submitted_at || new Date().toISOString(),
    data.razon_social || '',
    data.nombre_representante || '',
    data.nombre_para_stand || '',
    data.ciudad_origen || '',
    data.whatsapp || '',
    data.correo || '',
    data.redes || '',
    data.productos || '',
    data.categoria || '',
    data.stands_interes || '',
    data.archivos_productos || '',
    data.carpeta_drive || '',
    data.telefono_chat || ''
  ]);

  return { ok: true };
}

function updateConfirmedStand(body) {
  const sheet = getSheet();
  ensureHeaders(sheet);

  const row = findMatchingRow(sheet, body.query || '', body.representative || '');
  if (!row) {
    return { ok: false, error: 'No encontre una fila que coincida con la marca, razon social o representante.' };
  }

  const headers = headerIndexMap(sheet);
  sheet.getRange(row, headers['Stand confirmado']).setValue(String(body.stand || '').trim());
  sheet.getRange(row, headers['Estado administrativo']).setValue(body.status || 'stand confirmado');
  sheet.getRange(row, headers['Fecha confirmacion']).setValue(body.updated_at || new Date().toISOString());
  sheet.getRange(row, headers['Confirmado por']).setValue(body.confirmed_by || 'Ori admin');

  return { ok: true, row: row };
}

function deletePreinscriptionByChatPhone(body) {
  const phone = normalizePhone(body.phone || '');
  if (!phone) {
    return { ok: false, error: 'Falta phone' };
  }

  const sheet = getSheet();
  ensureHeaders(sheet);
  const headers = headerIndexMap(sheet);
  const phoneColumn = headers['Telefono chat'];
  if (!phoneColumn) {
    return { ok: true, deleted: 0 };
  }

  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) {
    return { ok: true, deleted: 0 };
  }

  const values = sheet.getRange(2, phoneColumn, lastRow - 1, 1).getValues();
  const rowsToDelete = [];
  values.forEach((row, index) => {
    const rowPhone = normalizePhone(row[0]);
    if (phonesMatch(rowPhone, phone)) {
      rowsToDelete.push(index + 2);
    }
  });

  rowsToDelete.reverse().forEach(rowNumber => sheet.deleteRow(rowNumber));
  return { ok: true, deleted: rowsToDelete.length };
}

function listPreinscriptions() {
  const sheet = getSheet();
  ensureHeaders(sheet);
  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) {
    return { ok: true, records: [] };
  }

  const headers = values[0].map(value => String(value || '').trim());
  const records = values.slice(1)
    .filter(row => row.some(value => String(value || '').trim()))
    .map(row => {
      const record = {};
      headers.forEach((header, index) => {
        record[header || `Columna ${index + 1}`] = row[index] instanceof Date
          ? row[index].toISOString()
          : String(row[index] || '');
      });
      return record;
    });

  return { ok: true, records: records };
}

function appendConversationLog(body) {
  const event = body.event || {};
  const sheet = getConversationLogSheet();
  ensureConversationLogHeaders(sheet);

  sheet.appendRow([
    body.created_at || new Date().toISOString(),
    event.phone || '',
    event.direction || '',
    event.message_type || '',
    event.body || '',
    event.button_id || '',
    event.media_type || '',
    event.media_id || '',
    event.role || '',
    event.brand || '',
    event.category || '',
    event.product || '',
    event.city || '',
    event.lead_stage || '',
    event.selected_stand || '',
    event.confirmed_stand || '',
    event.form_submitted === true ? 'Si' : '',
    event.internal === true ? 'Si' : '',
    event.phone_number_id || '',
    event.display_phone_number || '',
    event.extra || ''
  ]);

  return { ok: true };
}

function uploadFile(body) {
  const parentId = body.drive_folder_id;
  if (!parentId) {
    throw new Error('Falta drive_folder_id');
  }

  const legalName = cleanFolderName(body.legal_name || 'Sin razon social');
  const parent = DriveApp.getFolderById(parentId);
  const folder = getOrCreateFolder(parent, legalName);
  const bytes = Utilities.base64Decode(body.base64 || '');
  const blob = Utilities.newBlob(bytes, body.mime_type || 'application/octet-stream', body.filename || 'archivo');
  const file = folder.createFile(blob);

  return {
    ok: true,
    file_url: file.getUrl(),
    folder_url: folder.getUrl(),
    filename: file.getName()
  };
}

function getSheet() {
  const configuredId = PropertiesService.getScriptProperties().getProperty('FORM_RESPONSES_SHEET_ID') || SPREADSHEET_ID;
  const spreadsheet = configuredId
    ? SpreadsheetApp.openById(configuredId)
    : SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(SHEET_NAME);
  }
  return sheet;
}

function getConversationLogSheet() {
  const configuredId = PropertiesService.getScriptProperties().getProperty('FORM_RESPONSES_SHEET_ID') || SPREADSHEET_ID;
  const spreadsheet = configuredId
    ? SpreadsheetApp.openById(configuredId)
    : SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(CONVERSATION_LOG_SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(CONVERSATION_LOG_SHEET_NAME);
  }
  return sheet;
}

function ensureHeaders(sheet) {
  const headers = [
    'Fecha',
    'Razon social',
    'Nombre representante',
    'Nombre para el stand',
    'Ciudad de origen',
    'Whatsapp',
    'Direccion de correo electronico',
    'Redes sociales y/o pagina web',
    'Productos a participar',
    'Categoria',
    'Stands de interes',
    'Archivos de productos',
    'Carpeta Drive',
    'Telefono chat',
    'Stand confirmado',
    'Estado administrativo',
    'Fecha confirmacion',
    'Confirmado por'
  ];

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(headers);
    return;
  }

  const current = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), headers.length)).getValues()[0];
  const isEmpty = current.every(value => !value);
  if (isEmpty) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    return;
  }

  const existing = current.map(value => String(value || '').trim());
  headers.forEach(header => {
    if (existing.indexOf(header) === -1) {
      sheet.getRange(1, sheet.getLastColumn() + 1).setValue(header);
      existing.push(header);
    }
  });
}

function ensureConversationLogHeaders(sheet) {
  const headers = [
    'Fecha',
    'Telefono',
    'Direccion',
    'Tipo mensaje',
    'Mensaje',
    'Boton ID',
    'Tipo archivo',
    'Archivo ID',
    'Rol',
    'Marca',
    'Categoria',
    'Producto',
    'Ciudad',
    'Etapa',
    'Stand seleccionado',
    'Stand confirmado',
    'Formulario enviado',
    'Interno admin',
    'Phone number ID',
    'Numero receptor',
    'Extra'
  ];

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(headers);
    return;
  }

  const current = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), headers.length)).getValues()[0];
  const isEmpty = current.every(value => !value);
  if (isEmpty) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    return;
  }

  const existing = current.map(value => String(value || '').trim());
  headers.forEach(header => {
    if (existing.indexOf(header) === -1) {
      sheet.getRange(1, sheet.getLastColumn() + 1).setValue(header);
      existing.push(header);
    }
  });
}

function headerIndexMap(sheet) {
  ensureHeaders(sheet);
  const values = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const output = {};
  values.forEach((value, index) => {
    const header = String(value || '').trim();
    if (header) {
      output[header] = index + 1;
    }
  });
  return output;
}

function findMatchingRow(sheet, query, representative) {
  const headers = headerIndexMap(sheet);
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) {
    return null;
  }

  const target = normalizeText(query);
  const representativeTarget = normalizeText(representative);
  const data = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();

  let bestRow = null;
  let bestScore = 0;
  data.forEach((row, index) => {
    const candidates = [
      [row[(headers['Razon social'] || 1) - 1], 4],
      [row[(headers['Nombre para el stand'] || 1) - 1], 4],
      [row[(headers['Nombre representante'] || 1) - 1], 3],
      [row[(headers['Whatsapp'] || 1) - 1], 2],
      [row[(headers['Telefono chat'] || 1) - 1], 2]
    ];
    let score = 0;
    candidates.forEach(item => {
      score = Math.max(score, matchScore(target, normalizeText(item[0]), item[1]));
      if (representativeTarget) {
        score = Math.max(score, matchScore(representativeTarget, normalizeText(item[0]), item[1]));
      }
    });
    if (score > bestScore) {
      bestScore = score;
      bestRow = index + 2;
    }
  });

  return bestScore >= 3 ? bestRow : null;
}

function matchScore(target, value, weight) {
  if (!target || !value) {
    return 0;
  }
  if (target === value) {
    return 5 * weight;
  }
  if (target.indexOf(value) !== -1 || value.indexOf(target) !== -1) {
    return 3 * weight;
  }
  return 0;
}

function normalizeText(value) {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9@.]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizePhone(value) {
  return String(value || '').replace(/\D+/g, '');
}

function phonesMatch(left, right) {
  if (!left || !right) {
    return false;
  }
  if (left === right) {
    return true;
  }
  return left.slice(-10) === right.slice(-10);
}

function getOrCreateFolder(parent, name) {
  const existing = parent.getFoldersByName(name);
  if (existing.hasNext()) {
    return existing.next();
  }
  return parent.createFolder(name);
}

function cleanFolderName(value) {
  return String(value)
    .replace(/[\\/:*?"<>|#%{}~&]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .substring(0, 120) || 'Sin razon social';
}

function jsonResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
