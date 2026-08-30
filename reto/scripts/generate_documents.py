# 1. Instalar librería para generación de PDF
%pip install reportlab --quiet

import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# 2. Configurar estructura en Unity Catalog y volumen

PATH = "/Volumes/andina_source/landing/files/pdf"
os.makedirs(PATH, exist_ok=True)

# 3. Contenido de los documentos para Andina Market
documents_data = {
    "politica_devoluciones_y_garantias.pdf": [
        ("Título", "Política de Devoluciones y Garantías - Andina Market"),
        ("Subtítulo", "Plazos y Solicitud de Devolución"),
        ("Texto", "Los clientes de Andina Market pueden solicitar la devolución de cualquier producto comprado a través de la web, app móvil o tienda física dentro de los 30 días posteriores a la recepción."),
        ("Subtítulo", "Requisitos del Producto"),
        ("Texto", "- El artículo debe estar sin uso, en su empaque original y con todas las etiquetas intactas.<br/>- Se debe presentar el comprobante de compra (factura digital o boleta)."),
        ("Subtítulo", "Proceso de Reembolso"),
        ("Texto", "El reembolso se procesará dentro de los 5 a 10 días hábiles posteriores a la recepción del paquete devuelto en el centro de distribución, acreditándose en el mismo método de pago utilizado."),
        ("Subtítulo", "Cobertura de Garantía por Defecto"),
        ("Texto", "Todos los productos del catálogo cuentan con 12 meses de garantía oficial por fallas de fabricación. La garantía no cubre daños por mal uso, caídas o humedad.")
    ],
    "politica_envios_y_logistica.pdf": [
        ("Título", "Políticas de Envío y Entregas - Andina Market"),
        ("Subtítulo", "Modalidades de Envío"),
        ("Texto", "- Envío Express: Disponible para ciudades principales con entrega en 24 a 48 horas hábiles.<br/>- Envío Estándar: Cobertura nacional con entrega entre 3 a 5 días hábiles.<br/>- Retiro en Tienda (Click & Collect): Gratis en cualquier sucursal física de Andina Market tras recibir la notificación de confirmación."),
        ("Subtítulo", "Costos de Envío"),
        ("Texto", "Los envíos son gratuitos para compras superiores a $50 USD (o su equivalente local). Para compras de menor monto, la tarifa se calcula en el checkout según el destino.")
    ],
    "faq_cuenta_pagos_y_pedidos.pdf": [
        ("Título", "Preguntas Frecuentes (FAQs) - Andina Market"),
        ("Subtítulo", "¿Qué medios de pago puedo utilizar?"),
        ("Texto", "Aceptamos tarjetas de crédito y débito (Visa, Mastercard, Amex), billeteras digitales (Yape, Plin, Mercado Pago) y transferencias bancarias directas."),
        ("Subtítulo", "¿Cómo puedo realizar el seguimiento de mi pedido?"),
        ("Texto", "Puedes consultar el estado en tiempo real ingresando a la sección 'Mis Pedidos' en la App o sitio web de Andina Market, o mediante el enlace de rastreo enviado a tu correo."),
        ("Subtítulo", "¿Puedo cancelar un pedido?"),
        ("Texto", "La cancelación es automática e inmediata si el pedido aún figura en estado 'En preparación'. Si ya fue despachado, deberás iniciar el proceso de devolución tras recibirlo.")
    ],
    "manual_producto_smart_tv_55.pdf": [
        ("Título", "Manual de Producto: Smart TV 55' 4K UHD - AndinaTech"),
        ("Subtítulo", "Especificaciones Principales"),
        ("Texto", "SKU: AT-TV55-4K<br/>Pantalla LED 55 pulgadas 4K UHD. Sistema Operativo integrado con soporte para apps de streaming. Conectividad: 3 puertos HDMI, 2 puertos USB, Wi-Fi y Ethernet."),
        ("Subtítulo", "Guía de Configuración Inicial"),
        ("Texto", "1. Conectar el televisor a la toma de corriente y encenderlo mediante el control remoto.<br/>2. Seleccionar el idioma y conectar la red Wi-Fi de su hogar.<br/>3. Iniciar sesión con su cuenta de Andina Market para vincular servicios de soporte y garantía."),
        ("Subtítulo", "Resolución de Problemas Frecuentes"),
        ("Texto", "- Sin señal de red: Reiniciar el router y verificar la contraseña introducida en el menú de red.<br/>- Sin sonido: Comprobar que la salida de audio no esté configurada en altavoces externos o en modo Mute.")
    ],
    "manual_producto_laptop_pro_15.pdf": [
        ("Título", "Manual de Producto: Laptop Pro 15' - AndinaTech"),
        ("Subtítulo", "Especificaciones Técnicas"),
        ("Texto", "SKU: AT-LAP15-PRO<br/>Procesador Octa-Core de alto rendimiento. 16 GB RAM / 512 GB SSD almacenamiento. Pantalla Full HD IPS 15.6 pulgadas."),
        ("Subtítulo", "Recomendaciones de Cuidado y Uso"),
        ("Texto", "Cargar la batería al 100% antes del primer uso. Limpiar la pantalla únicamente con un paño de microfibra seco. Evitar obstruir las rejillas de ventilación inferiores mientras esté encendida."),
        ("Subtítulo", "Soporte Técnico"),
        ("Texto", "Si el equipo presenta fallas de encendido o pantalla congelada, mantenga presionado el botón de encendido durante 10 segundos para forzar el reinicio. Si el problema persiste, inicie un ticket de soporte en la plataforma de Andina Market.")
    ]
}

# 4. Generación física de archivos PDF
styles = getSampleStyleSheet()
title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, spaceAfter=12)
heading_style = ParagraphStyle('HeadingStyle', parent=styles['Heading2'], fontSize=12, spaceAfter=8)
body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=10, spaceAfter=8)

for filename, content_blocks in documents_data.items():
    filepath = os.path.join(PATH, filename)
    doc = SimpleDocTemplate(filepath, pagesize=letter)
    story = []

    for block_type, text in content_blocks:
        if block_type == "Título":
            story.append(Paragraph(text, title_style))
        elif block_type == "Subtítulo":
            story.append(Paragraph(text, heading_style))
        else:
            story.append(Paragraph(text, body_style))
        story.append(Spacer(1, 4))

    doc.build(story)

print(f"✅ Se han creado {len(documents_data)} archivos PDF binarios reales en: {PATH}")