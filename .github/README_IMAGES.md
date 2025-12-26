# B3 DateTime API - Assets

Este diretório contém os recursos visuais do projeto.

## 📁 Arquivos Disponíveis

### Logo
- **logo.svg** - Logo completo horizontal (400x120px) para README e documentação

### Ícones
- **icon.svg** - Ícone completo (512x512px) com detalhes para aplicações
- **icon-simple.svg** - Ícone simplificado (256x256px) para uso em tamanhos menores

## 🎨 Como Usar

### No README
```markdown
![B3 DateTime API](.github/logo.svg)
```

### Como Favicon
Para converter o ícone SVG em PNG/ICO para favicon, use ferramentas como:

**ImageMagick:**
```bash
# Gerar PNG em diferentes tamanhos
convert .github/icon-simple.svg -resize 16x16 favicon-16.png
convert .github/icon-simple.svg -resize 32x32 favicon-32.png
convert .github/icon-simple.svg -resize 180x180 apple-touch-icon.png
convert .github/icon-simple.svg -resize 512x512 icon-512.png
```

**Online:**
- [Favicon Generator](https://favicon.io/favicon-converter/)
- [Real Favicon Generator](https://realfavicongenerator.net/)

### Em Aplicações
Use os arquivos SVG diretamente ou converta para PNG nos tamanhos necessários:
- **16x16, 32x32** - Favicon
- **180x180** - Apple Touch Icon
- **192x192, 512x512** - PWA Icons
- **1024x1024** - App Store / Play Store

## 🎨 Paleta de Cores

- **Azul Escuro**: `#1e40af`
- **Azul Médio**: `#3b82f6`
- **Azul Claro**: `#60a5fa`
- **Fundo**: `#0f172a`
- **Texto Secundário**: `#94a3b8`
- **Branco**: `#ffffff`

## 📝 Licença

Os assets deste projeto seguem a mesma licença do repositório principal.
