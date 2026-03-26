FROM node:20-alpine

WORKDIR /app

COPY package.json ./package.json
COPY apps/web/package.json ./apps/web/package.json
COPY packages/common/package.json ./packages/common/package.json

RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "-w", "@ai-office/web", "--", "--host", "0.0.0.0", "--port", "5173"]

