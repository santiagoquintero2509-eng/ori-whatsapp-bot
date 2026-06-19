const SHEET_NAME = 'Respuestas Ori';
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

    return jsonResponse({ ok: false, error: 'Accion no reconocida' });
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
    'Telefono chat'
  ];

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(headers);
    return;
  }

  const current = sheet.getRange(1, 1, 1, headers.length).getValues()[0];
  const isEmpty = current.every(value => !value);
  if (isEmpty) {
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  }
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
