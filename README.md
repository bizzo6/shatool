# shatool



## Quick Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/bizzo6/shatool)

## Local Development

### Prerequisites

- Node.js (v14 or higher)
- npm or yarn
- WhatsApp Web account

### Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd whatsapp-web-monitor
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Create a `.env` file:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and add your API token.

4. Start the development server:
   ```bash
   npm run dev
   ```

5. Open your browser and go to `http://localhost:3000`

### Environment Variables

- `API_TOKEN`: Your API token for webhook authentication
- `PORT`: Port for the web interface (default: 3000)

## Usage

1. Start the application
2. Open the web interface at `http://localhost:3000`
3. Scan the QR code with your phone
4. Once authenticated, the app will start monitoring messages
5. View statistics and logs in the console

## Development

- `npm start`: Start the production server
- `npm run dev`: Start the development server with auto-reload
- `npm test`: Run tests (not implemented yet)
