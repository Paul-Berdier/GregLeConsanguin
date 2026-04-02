FROM node:20-alpine
WORKDIR /app
COPY services/web/package.json ./
RUN npm install
COPY services/web/ .
RUN npm run build
CMD ["npm", "start"]
